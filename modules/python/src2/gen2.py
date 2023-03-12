#!/usr/bin/env python

from __future__ import print_function
import hdr_parser, sys, re, os
from string import Template
from pprint import pprint

if sys.version_info[0] >= 3:
    from io import StringIO
else:
    from cStringIO import StringIO

forbidden_arg_types = ["void*"]

ignored_arg_types = ["RNG*"]

pass_by_val_types = ["Point*", "Point2f*", "Rect*", "String*", "double*", "float*", "int*"]

gen_template_check_self = Template("""    $cname* _self_ = NULL;
    if(PyObject_TypeCheck(self, &pyopencv_${name}_Type))
        _self_ = ${amp}((pyopencv_${name}_t*)self)->v${get};
    if (!_self_)
        return failmsgp("Incorrect type of self (must be '${name}' or its derivative)");
""")

gen_template_check_self_algo = Template("""    $cname* _self_ = NULL;
    if(PyObject_TypeCheck(self, &pyopencv_${name}_Type))
        _self_ = dynamic_cast<$cname*>(${amp}((pyopencv_${name}_t*)self)->v.get());
    if (!_self_)
        return failmsgp("Incorrect type of self (must be '${name}' or its derivative)");
""")

gen_template_call_constructor_prelude = Template("""new (&(self->v)) Ptr<$cname>(); // init Ptr with placement new
        if(self) """)

gen_template_call_constructor = Template("""self->v.reset(new ${cname}${args})""")

gen_template_simple_call_constructor_prelude = Template("""if(self) """)

gen_template_simple_call_constructor = Template("""new (&(self->v)) ${cname}${args}""")

gen_template_parse_args = Template("""const char* keywords[] = { $kw_list, NULL };
    if( PyArg_ParseTupleAndKeywords(args, kw, "$fmtspec", (char**)keywords, $parse_arglist)$code_cvt )""")

gen_template_func_body = Template("""$code_decl
    $code_parse
    {
        ${code_prelude}ERRWRAP2($code_fcall);
        $code_ret;
    }
""")

head_init_str = "CV_PYTHON_TYPE_HEAD_INIT()"

gen_template_simple_type_decl = Template("""
struct pyopencv_${name}_t
{
    PyObject_HEAD
    ${cname} v;
};

static PyTypeObject pyopencv_${name}_Type =
{
    %s
    MODULESTR".$wname",
    sizeof(pyopencv_${name}_t),
};

static void pyopencv_${name}_dealloc(PyObject* self)
{
    ((pyopencv_${name}_t*)self)->v.${cname}::~${sname}();
    PyObject_Del(self);
}

template<>
struct PyOpenCV_Converter< ${cname} >
{
    static PyObject* from(const ${cname}& r)
    {
        pyopencv_${name}_t *m = PyObject_NEW(pyopencv_${name}_t, &pyopencv_${name}_Type);
        new (&m->v) ${cname}(r); //Copy constructor
        return (PyObject*)m;
    }

    static bool to(PyObject* src, ${cname}& dst, const char* name)
    {
        if(!src || src == Py_None)
            return true;
        if(PyObject_TypeCheck(src, &pyopencv_${name}_Type))
        {
            dst = ((pyopencv_${name}_t*)src)->v;
            return true;
        }
        failmsg("Expected ${cname} for argument '%%s'", name);
        return false;
    }
};
""" % head_init_str)

gen_template_mappable = Template("""
    {
        ${mappable} _src;
        if (pyopencv_to(src, _src, name))
        {
            return cv_mappable_to(_src, dst);
        }
    }
""")

gen_template_type_decl = Template("""
struct pyopencv_${name}_t
{
    PyObject_HEAD
    Ptr<${cname1}> v;
};

static PyTypeObject pyopencv_${name}_Type =
{
    %s
    MODULESTR".$wname",
    sizeof(pyopencv_${name}_t),
};

static void pyopencv_${name}_dealloc(PyObject* self)
{
    ((pyopencv_${name}_t*)self)->v.release();
    PyObject_Del(self);
}

template<>
struct PyOpenCV_Converter< Ptr<${cname}> >
{
    static PyObject* from(const Ptr<${cname}>& r)
    {
        pyopencv_${name}_t *m = PyObject_NEW(pyopencv_${name}_t, &pyopencv_${name}_Type);
        new (&(m->v)) Ptr<$cname1>(); // init Ptr with placement new
        m->v = r;
        return (PyObject*)m;
    }

    static bool to(PyObject* src, Ptr<${cname}>& dst, const char* name)
    {
        if(!src || src == Py_None)
            return true;
        if(PyObject_TypeCheck(src, &pyopencv_${name}_Type))
        {
            dst = ((pyopencv_${name}_t*)src)->v.dynamicCast<${cname}>();
            return true;
        }
        ${mappable_code}
        failmsg("Expected ${cname} for argument '%%s'", name);
        return false;
    }
};

""" % head_init_str)

gen_template_map_type_cvt = Template("""
template<> bool pyopencv_to(PyObject* src, ${cname}& dst, const char* name);
""")

gen_template_set_prop_from_map = Template("""
    if( PyMapping_HasKeyString(src, (char*)"$propname") )
    {
        tmp = PyMapping_GetItemString(src, (char*)"$propname");
        ok = tmp && pyopencv_to(tmp, dst.$propname);
        Py_DECREF(tmp);
        if(!ok) return false;
    }""")

gen_template_type_impl = Template("""
static PyObject* pyopencv_${name}_repr(PyObject* self)
{
    char str[1000];
    sprintf(str, "<$wname %p>", self);
    return PyString_FromString(str);
}

${getset_code}

static PyGetSetDef pyopencv_${name}_getseters[] =
{${getset_inits}
    {NULL}  /* Sentinel */
};

${methods_code}

static PyMethodDef pyopencv_${name}_methods[] =
{
${methods_inits}
    {NULL,          NULL}
};

static void pyopencv_${name}_specials(void)
{
    pyopencv_${name}_Type.tp_base = ${baseptr};
    pyopencv_${name}_Type.tp_dealloc = pyopencv_${name}_dealloc;
    pyopencv_${name}_Type.tp_repr = pyopencv_${name}_repr;
    pyopencv_${name}_Type.tp_getset = pyopencv_${name}_getseters;
    pyopencv_${name}_Type.tp_init = (initproc)${constructor};
    pyopencv_${name}_Type.tp_methods = pyopencv_${name}_methods;${extra_specials}
}
""")


gen_template_get_prop = Template("""
static PyObject* pyopencv_${name}_get_${member}(pyopencv_${name}_t* p, void *closure)
{
    return pyopencv_from(p->v${access}${member});
}
""")

gen_template_get_prop_algo = Template("""
static PyObject* pyopencv_${name}_get_${member}(pyopencv_${name}_t* p, void *closure)
{
    $cname* _self_ = dynamic_cast<$cname*>(p->v.get());
    if (!_self_)
        return failmsgp("Incorrect type of object (must be '${name}' or its derivative)");
    return pyopencv_from(_self_${access}${member});
}
""")

gen_template_set_prop = Template("""
static int pyopencv_${name}_set_${member}(pyopencv_${name}_t* p, PyObject *value, void *closure)
{
    if (!value)
    {
        PyErr_SetString(PyExc_TypeError, "Cannot delete the ${member} attribute");
        return -1;
    }
    return pyopencv_to(value, p->v${access}${member}) ? 0 : -1;
}
""")

gen_template_set_prop_algo = Template("""
static int pyopencv_${name}_set_${member}(pyopencv_${name}_t* p, PyObject *value, void *closure)
{
    if (!value)
    {
        PyErr_SetString(PyExc_TypeError, "Cannot delete the ${member} attribute");
        return -1;
    }
    $cname* _self_ = dynamic_cast<$cname*>(p->v.get());
    if (!_self_)
    {
        failmsgp("Incorrect type of object (must be '${name}' or its derivative)");
        return -1;
    }
    return pyopencv_to(value, _self_${access}${member}) ? 0 : -1;
}
""")


gen_template_prop_init = Template("""
    {(char*)"${member}", (getter)pyopencv_${name}_get_${member}, NULL, (char*)"${member}", NULL},""")

gen_template_rw_prop_init = Template("""
    {(char*)"${member}", (getter)pyopencv_${name}_get_${member}, (setter)pyopencv_${name}_set_${member}, (char*)"${member}", NULL},""")

simple_argtype_mapping = {
    "bool": ("bool", "b", "0"),
    "size_t": ("size_t", "I", "0"),
    "int": ("int", "i", "0"),
    "float": ("float", "f", "0.f"),
    "double": ("double", "d", "0"),
    "c_string": ("char*", "s", '(char*)""')
}

def normalize_class_name(name):
    return re.sub(r"^cv\.", "", name).replace(".", "_")

class ClassProp(object):
    def __init__(self, decl):
        self.tp = decl[0].replace("*", "_ptr")
        self.name = decl[1]
        self.readonly = True
        if "/RW" in decl[3]:
            self.readonly = False

class ClassInfo(object):
    def __init__(self, name, decl=None):
        self.cname = name.replace(".", "::")
        self.name = self.wname = normalize_class_name(name)
        self.sname = name[name.rfind('.') + 1:]
        self.ismap = False
        self.issimple = False
        self.isalgorithm = False
        self.methods = {}
        self.props = []
        self.mappables = []
        self.consts = {}
        self.base = None
        self.constructor = None
        customname = False

        if decl:
            bases = decl[1].split()[1:]
            if len(bases) > 1:
                print(
                    f"Note: Class {self.name} has more than 1 base class (not supported by Python C extensions)"
                )
                print("      Bases: ", " ".join(bases))
                print("      Only the first base class will be used")
                        #return sys.exit(-1)
            elif len(bases) == 1:
                self.base = bases[0].strip(",")
                if self.base.startswith("cv::"):
                    self.base = self.base[4:]
                if self.base == "Algorithm":
                    self.isalgorithm = True
                self.base = self.base.replace("::", "_")

            for m in decl[2]:
                if m.startswith("="):
                    self.wname = m[1:]
                    customname = True
                elif m == "/Map":
                    self.ismap = True
                elif m == "/Simple":
                    self.issimple = True
            self.props = [ClassProp(p) for p in decl[3]]

        if not customname and self.wname.startswith("Cv"):
            self.wname = self.wname[2:]

    def gen_map_code(self, codegen):
        all_classes = codegen.classes
        code = "static bool pyopencv_to(PyObject* src, %s& dst, const char* name)\n{\n    PyObject* tmp;\n    bool ok;\n" % (self.cname)
        code += "".join([gen_template_set_prop_from_map.substitute(propname=p.name,proptype=p.tp) for p in self.props])
        if self.base:
            code += "\n    return pyopencv_to(src, (%s&)dst, name);\n}\n" % all_classes[self.base].cname
        else:
            code += "\n    return true;\n}\n"
        return code

    def gen_code(self, codegen):
        all_classes = codegen.classes
        if self.ismap:
            return self.gen_map_code(codegen)

        getset_code = StringIO()
        getset_inits = StringIO()

        sorted_props = [(p.name, p) for p in self.props]
        sorted_props.sort()

        access_op = "." if self.issimple else "->"
        for pname, p in sorted_props:
            if self.isalgorithm:
                getset_code.write(gen_template_get_prop_algo.substitute(name=self.name, cname=self.cname, member=pname, membertype=p.tp, access=access_op))
            else:
                getset_code.write(gen_template_get_prop.substitute(name=self.name, member=pname, membertype=p.tp, access=access_op))
            if p.readonly:
                getset_inits.write(gen_template_prop_init.substitute(name=self.name, member=pname))
            else:
                if self.isalgorithm:
                    getset_code.write(gen_template_set_prop_algo.substitute(name=self.name, cname=self.cname, member=pname, membertype=p.tp, access=access_op))
                else:
                    getset_code.write(gen_template_set_prop.substitute(name=self.name, member=pname, membertype=p.tp, access=access_op))
                getset_inits.write(gen_template_rw_prop_init.substitute(name=self.name, member=pname))

        methods_code = StringIO()
        methods_inits = StringIO()

        sorted_methods = sorted(self.methods.items())
        if self.constructor is not None:
            methods_code.write(self.constructor.gen_code(codegen))

        for mname, m in sorted_methods:
            methods_code.write(m.gen_code(codegen))
            methods_inits.write(m.get_tab_entry())

        baseptr = "NULL"
        if self.base and self.base in all_classes:
            baseptr = f"&pyopencv_{all_classes[self.base].name}_Type"

        constructor_name = "0"
        if self.constructor is not None:
            constructor_name = self.constructor.get_wrapper_name()

        return gen_template_type_impl.substitute(
            name=self.name,
            wname=self.wname,
            cname=self.cname,
            getset_code=getset_code.getvalue(),
            getset_inits=getset_inits.getvalue(),
            methods_code=methods_code.getvalue(),
            methods_inits=methods_inits.getvalue(),
            baseptr=baseptr,
            constructor=constructor_name,
            extra_specials="",
        )


def handle_ptr(tp):
    if tp.startswith('Ptr_'):
        tp = 'Ptr<' + "::".join(tp.split('_')[1:]) + '>'
    return tp


class ArgInfo(object):
    def __init__(self, arg_tuple):
        self.tp = handle_ptr(arg_tuple[0])
        self.name = arg_tuple[1]
        self.defval = arg_tuple[2]
        self.isarray = False
        self.arraylen = 0
        self.arraycvt = None
        self.inputarg = True
        self.outputarg = False
        self.returnarg = False
        for m in arg_tuple[3]:
            if m == "/O":
                self.inputarg = False
                self.outputarg = True
                self.returnarg = True
            elif m == "/IO":
                self.inputarg = True
                self.outputarg = True
                self.returnarg = True
            elif m.startswith("/A"):
                self.isarray = True
                self.arraylen = m[2:].strip()
            elif m.startswith("/CA"):
                self.isarray = True
                self.arraycvt = m[2:].strip()
        self.py_inputarg = False
        self.py_outputarg = False

    def isbig(self):
        return self.tp in ["Mat", "vector_Mat", "cuda::GpuMat", "UMat", "vector_UMat"]

    def crepr(self):
        return "ArgInfo(\"%s\", %d)" % (self.name, self.outputarg)


class FuncVariant(object):
    def __init__(self, classname, name, decl, isconstructor, isphantom=False):
        self.classname = classname
        self.name = self.wname = name
        self.isconstructor = isconstructor
        self.isphantom = isphantom

        self.docstring = decl[5]

        self.rettype = decl[4] or handle_ptr(decl[1])
        if self.rettype == "void":
            self.rettype = ""
        self.args = []
        self.array_counters = {}
        for a in decl[3]:
            ainfo = ArgInfo(a)
            if ainfo.isarray and not ainfo.arraycvt:
                c = ainfo.arraylen
                if c_arrlist := self.array_counters.get(c, []):
                    c_arrlist.append(ainfo.name)
                else:
                    self.array_counters[c] = [ainfo.name]
            self.args.append(ainfo)
        self.init_pyproto()

    def init_pyproto(self):
        # string representation of argument list, with '[', ']' symbols denoting optional arguments, e.g.
        # "src1, src2[, dst[, mask]]" for cv.add
        argstr = ""

        # list of all input arguments of the Python function, with the argument numbers:
        #    [("src1", 0), ("src2", 1), ("dst", 2), ("mask", 3)]
        # we keep an argument number to find the respective argument quickly, because
        # some of the arguments of C function may not present in the Python function (such as array counters)
        # or even go in a different order ("heavy" output parameters of the C function
        # become the first optional input parameters of the Python function, and thus they are placed right after
        # non-optional input parameters)
        arglist = []

        # the list of "heavy" output parameters. Heavy parameters are the parameters
        # that can be expensive to allocate each time, such as vectors and matrices (see isbig).
        outarr_list = []

        # the list of output parameters. Also includes input/output parameters.
        outlist = []

        firstoptarg = 1000000
        argno = -1
        for a in self.args:
            argno += 1
            if a.name in self.array_counters:
                continue
            assert (
                a.tp not in forbidden_arg_types
            ), f'Forbidden type "{a.tp}" for argument "{a.name}" in "{self.name}" ("{self.classname}")'
            if a.tp in ignored_arg_types:
                continue
            if a.returnarg:
                outlist.append((a.name, argno))
            if (not a.inputarg) and a.isbig():
                outarr_list.append((a.name, argno))
                continue
            if not a.inputarg:
                continue
            if a.defval:
                firstoptarg = min(firstoptarg, len(arglist))
                # if there are some array output parameters before the first default parameter, they
                # are added as optional parameters before the first optional parameter
                if outarr_list:
                    arglist += outarr_list
                    outarr_list = []
            arglist.append((a.name, argno))
        if outarr_list:
            firstoptarg = min(firstoptarg, len(arglist))
            arglist += outarr_list
        firstoptarg = min(firstoptarg, len(arglist))

        noptargs = len(arglist) - firstoptarg
        argnamelist = [aname for aname, argno in arglist]
        argstr = ", ".join(argnamelist[:firstoptarg])
        argstr = "[, ".join([argstr] + argnamelist[firstoptarg:])
        argstr += "]" * noptargs
        if self.rettype:
            outlist = [("retval", -1)] + outlist
        elif self.isconstructor:
            assert not outlist
            outlist = [("self", -1)]
        if self.isconstructor:
            classname = self.classname
            if classname.startswith("Cv"):
                classname=classname[2:]
            outstr = f"<{classname} object>"
        elif outlist:
            outstr = ", ".join([o[0] for o in outlist])
        else:
            outstr = "None"

        self.py_arg_str = argstr
        self.py_return_str = outstr
        self.py_prototype = f"{self.wname}({argstr}) -> {outstr}"
        self.py_noptargs = noptargs
        self.py_arglist = arglist
        for aname, argno in arglist:
            self.args[argno].py_inputarg = True
        for aname, argno in outlist:
            if argno >= 0:
                self.args[argno].py_outputarg = True
        self.py_outlist = outlist


class FuncInfo(object):
    def __init__(self, classname, name, cname, isconstructor, namespace, is_static):
        self.classname = classname
        self.name = name
        self.cname = cname
        self.isconstructor = isconstructor
        self.namespace = namespace
        self.is_static = is_static
        self.variants = []

    def add_variant(self, decl, isphantom=False):
        self.variants.append(FuncVariant(self.classname, self.name, decl, self.isconstructor, isphantom))

    def get_wrapper_name(self):
        name = self.name
        if self.classname:
            classname = f"{self.classname}_"
            if "[" in name:
                name = "getelem"
        else:
            classname = ""

        if self.is_static:
            name += "_static"

        return "pyopencv_" + self.namespace.replace('.','_') + '_' + classname + name

    def get_wrapper_prototype(self, codegen):
        full_fname = self.get_wrapper_name()
        if self.isconstructor:
            return "static int {fn_name}(pyopencv_{type_name}_t* self, PyObject* args, PyObject* kw)".format(
                    fn_name=full_fname, type_name=codegen.classes[self.classname].name)

        self_arg = "self" if self.classname else ""
        return f"static PyObject* {full_fname}(PyObject* {self_arg}, PyObject* args, PyObject* kw)"

    def get_tab_entry(self):
        prototype_list = []
        docstring_list = []

        have_empty_constructor = False
        for v in self.variants:
            s = v.py_prototype
            if (not v.py_arglist) and self.isconstructor:
                have_empty_constructor = True
            if s not in prototype_list:
                prototype_list.append(s)
                docstring_list.append(v.docstring)

        # if there are just 2 constructors: default one and some other,
        # we simplify the notation.
        # Instead of ClassName(args ...) -> object or ClassName() -> object
        # we write ClassName([args ...]) -> object
        if have_empty_constructor and len(self.variants) == 2:
            idx = self.variants[1].py_arglist != []
            s = self.variants[idx].py_prototype
            p1 = s.find("(")
            p2 = s.rfind(")")
            prototype_list = [f"{s[:p1 + 1]}[{s[p1 + 1:p2]}]{s[p2:]}"]

        full_docstring = "".join(
            Template("$prototype\n$docstring\n\n\n\n").substitute(
                prototype=prototype,
                docstring='\n'.join([f'.   {line}' for line in body.split('\n')]),
            )
            for prototype, body in zip(prototype_list, docstring_list)
        )
        # Escape backslashes, newlines, and double quotes
        full_docstring = full_docstring.strip().replace("\\", "\\\\").replace('\n', '\\n').replace("\"", "\\\"")
        # Convert unicode chars to xml representation, but keep as string instead of bytes
        full_docstring = full_docstring.encode('ascii', errors='xmlcharrefreplace').decode()

        return Template('    {"$py_funcname", CV_PY_FN_WITH_KW_($wrap_funcname, $flags), "$py_docstring"},\n'
                        ).substitute(py_funcname = self.variants[0].wname, wrap_funcname=self.get_wrapper_name(),
                                     flags = 'METH_STATIC' if self.is_static else '0', py_docstring = full_docstring)

    def gen_code(self, codegen):
        all_classes = codegen.classes
        proto = self.get_wrapper_prototype(codegen)
        code = "%s\n{\n" % (proto,)
        code += "    using namespace %s;\n\n" % self.namespace.replace('.', '::')

        selfinfo = ClassInfo("")
        ismethod = self.classname != "" and not self.isconstructor
        # full name is needed for error diagnostic in PyArg_ParseTupleAndKeywords
        fullname = self.name

        if self.classname:
            selfinfo = all_classes[self.classname]
            if not self.isconstructor:
                amp = "&" if selfinfo.issimple else ""
                if self.is_static:
                    pass
                elif selfinfo.isalgorithm:
                    code += gen_template_check_self_algo.substitute(name=selfinfo.name, cname=selfinfo.cname, amp=amp)
                else:
                    get = "" if selfinfo.issimple else ".get()"
                    code += gen_template_check_self.substitute(name=selfinfo.name, cname=selfinfo.cname, amp=amp, get=get)
                fullname = selfinfo.wname + "." + fullname

        all_code_variants = []
        declno = -1
        for v in self.variants:
            code_decl = ""
            code_ret = ""
            code_cvt_list = []

            code_args = "("
            all_cargs = []
            parse_arglist = []

            if v.isphantom and ismethod and not self.is_static:
                code_args += "_self_"

            # declare all the C function arguments,
            # add necessary conversions from Python objects to code_cvt_list,
            # form the function/method call,
            # for the list of type mappings
            for a in v.args:
                if a.tp in ignored_arg_types:
                    defval = a.defval
                    if not defval and a.tp.endswith("*"):
                        defval = "0"
                    assert defval
                    if not code_args.endswith("("):
                        code_args += ", "
                    code_args += defval
                    all_cargs.append([[None, ""], ""])
                    continue
                tp1 = tp = a.tp
                amp = ""
                defval0 = ""
                if tp in pass_by_val_types:
                    tp = tp1 = tp[:-1]
                    amp = "&"
                    if tp.endswith("*"):
                        defval0 = "0"
                        tp1 = tp.replace("*", "_ptr")
                tp_candidates = [a.tp, normalize_class_name(self.namespace + "." + a.tp)]
                if any(tp in codegen.enums.keys() for tp in tp_candidates):
                    defval0 = "static_cast<%s>(%d)" % (a.tp, 0)

                amapping = simple_argtype_mapping.get(tp, (tp, "O", defval0))
                parse_name = a.name
                if a.py_inputarg:
                    if amapping[1] == "O":
                        code_decl += "    PyObject* pyobj_%s = NULL;\n" % (a.name,)
                        parse_name = "pyobj_" + a.name
                        if a.tp == 'char':
                            code_cvt_list.append("convert_to_char(pyobj_%s, &%s, %s)"% (a.name, a.name, a.crepr()))
                        else:
                            code_cvt_list.append("pyopencv_to(pyobj_%s, %s, %s)" % (a.name, a.name, a.crepr()))

                all_cargs.append([amapping, parse_name])

                defval = a.defval
                if not defval:
                    defval = amapping[2]
                else:
                    if "UMat" in tp:
                        if "Mat" in defval and "UMat" not in defval:
                            defval = defval.replace("Mat", "UMat")
                    if "cuda::GpuMat" in tp:
                        if "Mat" in defval and "GpuMat" not in defval:
                            defval = defval.replace("Mat", "cuda::GpuMat")
                # "tp arg = tp();" is equivalent to "tp arg;" in the case of complex types
                if defval == tp + "()" and amapping[1] == "O":
                    defval = ""
                if a.outputarg and not a.inputarg:
                    defval = ""
                if defval:
                    code_decl += "    %s %s=%s;\n" % (amapping[0], a.name, defval)
                else:
                    code_decl += "    %s %s;\n" % (amapping[0], a.name)

                if not code_args.endswith("("):
                    code_args += ", "
                code_args += amp + a.name

            code_args += ")"

            if self.isconstructor:
                if selfinfo.issimple:
                    templ_prelude = gen_template_simple_call_constructor_prelude
                    templ = gen_template_simple_call_constructor
                else:
                    templ_prelude = gen_template_call_constructor_prelude
                    templ = gen_template_call_constructor

                code_prelude = templ_prelude.substitute(name=selfinfo.name, cname=selfinfo.cname)
                code_fcall = templ.substitute(name=selfinfo.name, cname=selfinfo.cname, args=code_args)
                if v.isphantom:
                    code_fcall = code_fcall.replace("new " + selfinfo.cname, self.cname.replace("::", "_"))
            else:
                code_prelude = ""
                code_fcall = ""
                if v.rettype:
                    code_decl += "    " + v.rettype + " retval;\n"
                    code_fcall += "retval = "
                if not v.isphantom and ismethod and not self.is_static:
                    code_fcall += "_self_->" + self.cname
                else:
                    code_fcall += self.cname
                code_fcall += code_args

            if code_cvt_list:
                code_cvt_list = [""] + code_cvt_list

            # add info about return value, if any, to all_cargs. if there non-void return value,
            # it is encoded in v.py_outlist as ("retval", -1) pair.
            # As [-1] in Python accesses the last element of a list, we automatically handle the return value by
            # adding the necessary info to the end of all_cargs list.
            if v.rettype:
                tp = v.rettype
                tp1 = tp.replace("*", "_ptr")
                amapping = simple_argtype_mapping.get(tp, (tp, "O", "0"))
                all_cargs.append(amapping)

            if v.args and v.py_arglist:
                # form the format spec for PyArg_ParseTupleAndKeywords
                fmtspec = "".join([all_cargs[argno][0][1] for aname, argno in v.py_arglist])
                if v.py_noptargs > 0:
                    fmtspec = fmtspec[:-v.py_noptargs] + "|" + fmtspec[-v.py_noptargs:]
                fmtspec += ":" + fullname

                # form the argument parse code that:
                #   - declares the list of keyword parameters
                #   - calls PyArg_ParseTupleAndKeywords
                #   - converts complex arguments from PyObject's to native OpenCV types
                code_parse = gen_template_parse_args.substitute(
                    kw_list = ", ".join(['"' + aname + '"' for aname, argno in v.py_arglist]),
                    fmtspec = fmtspec,
                    parse_arglist = ", ".join(["&" + all_cargs[argno][1] for aname, argno in v.py_arglist]),
                    code_cvt = " &&\n        ".join(code_cvt_list))
            else:
                code_parse = "if(PyObject_Size(args) == 0 && (!kw || PyObject_Size(kw) == 0))"

            if len(v.py_outlist) == 0:
                code_ret = "Py_RETURN_NONE"
            elif len(v.py_outlist) == 1:
                if self.isconstructor:
                    code_ret = "return 0"
                else:
                    aname, argno = v.py_outlist[0]
                    code_ret = "return pyopencv_from(%s)" % (aname,)
            else:
                # ther is more than 1 return parameter; form the tuple out of them
                fmtspec = "N"*len(v.py_outlist)
                backcvt_arg_list = []
                for aname, argno in v.py_outlist:
                    amapping = all_cargs[argno][0]
                    backcvt_arg_list.append("%s(%s)" % (amapping[2], aname))
                code_ret = "return Py_BuildValue(\"(%s)\", %s)" % \
                    (fmtspec, ", ".join(["pyopencv_from(" + aname + ")" for aname, argno in v.py_outlist]))

            all_code_variants.append(gen_template_func_body.substitute(code_decl=code_decl,
                code_parse=code_parse, code_prelude=code_prelude, code_fcall=code_fcall, code_ret=code_ret))

        if len(all_code_variants)==1:
            # if the function/method has only 1 signature, then just put it
            code += all_code_variants[0]
        else:
            # try to execute each signature
            code += "    PyErr_Clear();\n\n".join(["    {\n" + v + "    }\n" for v in all_code_variants])

        def_ret = "NULL"
        if self.isconstructor:
            def_ret = "-1"
        code += "\n    return %s;\n}\n\n" % def_ret

        cname = self.cname
        classinfo = None
        #dump = False
        #if dump: pprint(vars(self))
        #if dump: pprint(vars(self.variants[0]))
        if self.classname:
            classinfo = all_classes[self.classname]
            #if dump: pprint(vars(classinfo))
            if self.isconstructor:
                py_name = 'cv.' + classinfo.wname
            elif self.is_static:
                py_name = '.'.join([self.namespace, classinfo.sname + '_' + self.variants[0].wname])
            else:
                cname = classinfo.cname + '::' + cname
                py_name = 'cv.' + classinfo.wname + '.' + self.variants[0].wname
        else:
            py_name = '.'.join([self.namespace, self.variants[0].wname])
        #if dump: print(cname + " => " + py_name)
        py_signatures = codegen.py_signatures.setdefault(cname, [])
        for v in self.variants:
            s = dict(name=py_name, arg=v.py_arg_str, ret=v.py_return_str)
            for old in py_signatures:
                if s == old:
                    break
            else:
                py_signatures.append(s)

        return code


class Namespace(object):
    def __init__(self):
        self.funcs = {}
        self.consts = {}


class PythonWrapperGenerator(object):
    def __init__(self):
        self.clear()

    def clear(self):
        self.classes = {}
        self.namespaces = {}
        self.consts = {}
        self.enums = {}
        self.code_include = StringIO()
        self.code_enums = StringIO()
        self.code_types = StringIO()
        self.code_funcs = StringIO()
        self.code_type_reg = StringIO()
        self.code_ns_reg = StringIO()
        self.code_type_publish = StringIO()
        self.py_signatures = dict()
        self.class_idx = 0

    def add_class(self, stype, name, decl):
        classinfo = ClassInfo(name, decl)
        classinfo.decl_idx = self.class_idx
        self.class_idx += 1

        if classinfo.name in self.classes:
            print("Generator error: class %s (cname=%s) already exists" \
                % (classinfo.name, classinfo.cname))
            sys.exit(-1)
        self.classes[classinfo.name] = classinfo

        # Add Class to json file.
        namespace, classes, name = self.split_decl_name(name)
        namespace = '.'.join(namespace)
        name = '_'.join(classes+[name])

        py_name = 'cv.' + classinfo.wname  # use wrapper name
        py_signatures = self.py_signatures.setdefault(classinfo.cname, [])
        py_signatures.append(dict(name=py_name))
        #print('class: ' + classinfo.cname + " => " + py_name)

    def split_decl_name(self, name):
        chunks = name.split('.')
        namespace = chunks[:-1]
        classes = []
        while namespace and '.'.join(namespace) not in self.parser.namespaces:
            classes.insert(0, namespace.pop())
        return namespace, classes, chunks[-1]


    def add_const(self, name, decl):
        cname = name.replace('.','::')
        namespace, classes, name = self.split_decl_name(name)
        namespace = '.'.join(namespace)
        name = '_'.join(classes+[name])
        ns = self.namespaces.setdefault(namespace, Namespace())
        if name in ns.consts:
            print("Generator error: constant %s (cname=%s) already exists" \
                % (name, cname))
            sys.exit(-1)
        ns.consts[name] = cname

        value = decl[1]
        py_name = '.'.join([namespace, name])
        py_signatures = self.py_signatures.setdefault(cname, [])
        py_signatures.append(dict(name=py_name, value=value))
        #print(cname + ' => ' + str(py_name) + ' (value=' + value + ')')

    def add_enum(self, name, decl):
        wname = normalize_class_name(name)
        if wname.endswith("<unnamed>"):
            wname = None
        else:
            self.enums[wname] = name
        const_decls = decl[3]

        for decl in const_decls:
            name = decl[0]
            self.add_const(name.replace("const ", "").strip(), decl)

    def add_func(self, decl):
        namespace, classes, barename = self.split_decl_name(decl[0])
        cname = "::".join(namespace+classes+[barename])
        name = barename
        classname = ''
        bareclassname = ''
        if classes:
            classname = normalize_class_name('.'.join(namespace+classes))
            bareclassname = classes[-1]
        namespace = '.'.join(namespace)

        isconstructor = name == bareclassname
        is_static = False
        isphantom = False
        mappable = None
        for m in decl[2]:
            if m == "/S":
                is_static = True
            elif m == "/phantom":
                isphantom = True
                cname = cname.replace("::", "_")
            elif m.startswith("="):
                name = m[1:]
            elif m.startswith("/mappable="):
                mappable = m[10:]
                self.classes[classname].mappables.append(mappable)
                return

        if isconstructor:
            name = "_".join(classes[:-1]+[name])

        if is_static:
            # Add it as a method to the class
            func_map = self.classes[classname].methods
            func = func_map.setdefault(name, FuncInfo(classname, name, cname, isconstructor, namespace, is_static))
            func.add_variant(decl, isphantom)

            # Add it as global function
            g_name = "_".join(classes+[name])
            func_map = self.namespaces.setdefault(namespace, Namespace()).funcs
            func = func_map.setdefault(g_name, FuncInfo("", g_name, cname, isconstructor, namespace, False))
            func.add_variant(decl, isphantom)
        else:
            if classname and not isconstructor:
                if not isphantom:
                    cname = barename
                func_map = self.classes[classname].methods
            else:
                func_map = self.namespaces.setdefault(namespace, Namespace()).funcs

            func = func_map.setdefault(name, FuncInfo(classname, name, cname, isconstructor, namespace, is_static))
            func.add_variant(decl, isphantom)

        if classname and isconstructor:
            self.classes[classname].constructor = func


    def gen_namespace(self, ns_name):
        ns = self.namespaces[ns_name]
        wname = normalize_class_name(ns_name)

        self.code_ns_reg.write('static PyMethodDef methods_%s[] = {\n'%wname)
        for name, func in sorted(ns.funcs.items()):
            if func.isconstructor:
                continue
            self.code_ns_reg.write(func.get_tab_entry())
        self.code_ns_reg.write('    {NULL, NULL}\n};\n\n')

        self.code_ns_reg.write('static ConstDef consts_%s[] = {\n'%wname)
        for name, cname in sorted(ns.consts.items()):
            self.code_ns_reg.write('    {"%s", static_cast<long>(%s)},\n'%(name, cname))
            compat_name = re.sub(r"([a-z])([A-Z])", r"\1_\2", name).upper()
            if name != compat_name:
                self.code_ns_reg.write('    {"%s", static_cast<long>(%s)},\n'%(compat_name, cname))
        self.code_ns_reg.write('    {NULL, 0}\n};\n\n')

    def gen_namespaces_reg(self):
        self.code_ns_reg.write('static void init_submodules(PyObject * root) \n{\n')
        for ns_name in sorted(self.namespaces):
            if ns_name.split('.')[0] == 'cv':
                wname = normalize_class_name(ns_name)
                self.code_ns_reg.write('  init_submodule(root, MODULESTR"%s", methods_%s, consts_%s);\n' % (ns_name[2:], wname, wname))
        self.code_ns_reg.write('};\n')

    def gen_enum_reg(self, enum_name):
        name_seg = enum_name.split(".")
        is_enum_class = False
        if len(name_seg) >= 2 and name_seg[-1] == name_seg[-2]:
            enum_name = ".".join(name_seg[:-1])
            is_enum_class = True

        wname = normalize_class_name(enum_name)
        cname = enum_name.replace(".", "::")

        code = ""
        if re.sub(r"^cv\.", "", enum_name) != wname:
            code += "typedef {0} {1};\n".format(cname, wname)
        code += "CV_PY_FROM_ENUM({0});\nCV_PY_TO_ENUM({0});\n\n".format(wname)
        self.code_enums.write(code)

    def save(self, path, name, buf):
        with open(path + "/" + name, "wt") as f:
            f.write(buf.getvalue())

    def save_json(self, path, name, value):
        import json
        with open(path + "/" + name, "wt") as f:
            json.dump(value, f)

    def gen(self, srcfiles, output_path):
        self.clear()
        self.parser = hdr_parser.CppHeaderParser(generate_umat_decls=True, generate_gpumat_decls=True)

        # step 1: scan the headers and build more descriptive maps of classes, consts, functions
        for hdr in srcfiles:
            decls = self.parser.parse(hdr)
            if len(decls) == 0:
                continue
            if hdr.find('opencv2/') >= 0: #Avoid including the shadow files
                self.code_include.write( '#include "{0}"\n'.format(hdr[hdr.rindex('opencv2/'):]) )
            for decl in decls:
                name = decl[0]
                if name.startswith("struct") or name.startswith("class"):
                    # class/struct
                    p = name.find(" ")
                    stype = name[:p]
                    name = name[p+1:].strip()
                    self.add_class(stype, name, decl)
                elif name.startswith("const"):
                    # constant
                    self.add_const(name.replace("const ", "").strip(), decl)
                elif name.startswith("enum"):
                    # enum
                    self.add_enum(name.rsplit(" ", 1)[1], decl)
                else:
                    # function
                    self.add_func(decl)

        # step 1.5 check if all base classes exist
        for name, classinfo in self.classes.items():
            if classinfo.base:
                chunks = classinfo.base.split('_')
                base = '_'.join(chunks)
                while base not in self.classes and len(chunks)>1:
                    del chunks[-2]
                    base = '_'.join(chunks)
                if base not in self.classes:
                    print("Generator error: unable to resolve base %s for %s"
                        % (classinfo.base, classinfo.name))
                    sys.exit(-1)
                base_instance = self.classes[base]
                classinfo.base = base
                classinfo.isalgorithm |= base_instance.isalgorithm  # wrong processing of 'isalgorithm' flag:
                                                                    # doesn't work for trees(graphs) with depth > 2
                self.classes[name] = classinfo

        # tree-based propagation of 'isalgorithm'
        processed = dict()
        def process_isalgorithm(classinfo):
            if classinfo.isalgorithm or classinfo in processed:
                return classinfo.isalgorithm
            res = False
            if classinfo.base:
                res = process_isalgorithm(self.classes[classinfo.base])
                #assert not (res == True or classinfo.isalgorithm is False), "Internal error: " + classinfo.name + " => " + classinfo.base
                classinfo.isalgorithm |= res
                res = classinfo.isalgorithm
            processed[classinfo] = True
            return res
        for name, classinfo in self.classes.items():
            process_isalgorithm(classinfo)

        # step 2: generate code for the classes and their methods
        classlist = list(self.classes.items())
        classlist.sort()
        for name, classinfo in classlist:
            if classinfo.ismap:
                self.code_types.write(gen_template_map_type_cvt.substitute(name=name, cname=classinfo.cname))
            else:
                if classinfo.issimple:
                    templ = gen_template_simple_type_decl
                else:
                    templ = gen_template_type_decl
                mappable_code = "\n".join([
                                      gen_template_mappable.substitute(cname=classinfo.cname, mappable=mappable)
                                          for mappable in classinfo.mappables])
                self.code_types.write(templ.substitute(name=name, wname=classinfo.wname, cname=classinfo.cname, sname=classinfo.sname,
                                      cname1=("cv::Algorithm" if classinfo.isalgorithm else classinfo.cname), mappable_code=mappable_code))

        # register classes in the same order as they have been declared.
        # this way, base classes will be registered in Python before their derivatives.
        classlist1 = [(classinfo.decl_idx, name, classinfo) for name, classinfo in classlist]
        classlist1.sort()

        for decl_idx, name, classinfo in classlist1:
            code = classinfo.gen_code(self)
            self.code_types.write(code)
            if not classinfo.ismap:
                self.code_type_reg.write("MKTYPE2(%s);\n" % (classinfo.name,) )
                self.code_type_publish.write("PUBLISH_OBJECT(\"{name}\", pyopencv_{name}_Type);\n".format(name=classinfo.name))

        # step 3: generate the code for all the global functions
        for ns_name, ns in sorted(self.namespaces.items()):
            if ns_name.split('.')[0] != 'cv':
                continue
            for name, func in sorted(ns.funcs.items()):
                if func.isconstructor:
                    continue
                code = func.gen_code(self)
                self.code_funcs.write(code)
            self.gen_namespace(ns_name)
        self.gen_namespaces_reg()

        # step 4: generate the code for enum types
        enumlist = list(self.enums.values())
        enumlist.sort()
        for name in enumlist:
            self.gen_enum_reg(name)

        # step 5: generate the code for constants
        constlist = list(self.consts.items())
        constlist.sort()
        for name, constinfo in constlist:
            self.gen_const_reg(constinfo)

        # That's it. Now save all the files
        self.save(output_path, "pyopencv_generated_include.h", self.code_include)
        self.save(output_path, "pyopencv_generated_funcs.h", self.code_funcs)
        self.save(output_path, "pyopencv_generated_enums.h", self.code_enums)
        self.save(output_path, "pyopencv_generated_types.h", self.code_types)
        self.save(output_path, "pyopencv_generated_type_reg.h", self.code_type_reg)
        self.save(output_path, "pyopencv_generated_ns_reg.h", self.code_ns_reg)
        self.save(output_path, "pyopencv_generated_type_publish.h", self.code_type_publish)
        self.save_json(output_path, "pyopencv_signatures.json", self.py_signatures)

if __name__ == "__main__":
    srcfiles = hdr_parser.opencv_hdr_list
    dstdir = "/Users/vp/tmp"
    if len(sys.argv) > 1:
        dstdir = sys.argv[1]
    if len(sys.argv) > 2:
        srcfiles = [f.strip() for f in open(sys.argv[2], 'r').readlines()]
    generator = PythonWrapperGenerator()
    generator.gen(srcfiles, dstdir)
