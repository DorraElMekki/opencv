from __future__ import print_function
import sys, os, re

#
# Parser helpers
#

def remove_comments(s):
    def replacer(match):
        s = match.group(0)
        return "" if s.startswith('/') else s

    pattern = re.compile(
        r'//.*?$|/\*.*?\*/|\'(?:\\.|[^\\\'])*\'|"(?:\\.|[^\\"])*"',
        re.DOTALL | re.MULTILINE
    )
    return re.sub(pattern, replacer, s)


def getTokens(s):
    return re.findall(r'[a-z_A-Z0-9_]+|[^[a-z_A-Z0-9_ \n\r\t]', s)


def getParameter(pos, tokens):
    deep = 0
    p = []
    while pos < len(tokens):
        if tokens[pos] in [')', ','] and deep == 0:
            if tokens[pos] == ')':
                pos = len(tokens)
            else:
                pos += 1
            break
        if tokens[pos] == '(':
            deep += 1
        if tokens[pos] == ')':
            deep -= 1
        p.append(tokens[pos])
        pos += 1
    return (' '.join(p), pos)


def getParameters(i, tokens):
    assert tokens[i] == '('
    i += 1

    params = []
    while i < len(tokens) and tokens[i] != ')':
        (param, i) = getParameter(i, tokens)
        if len(param) > 0:
            params.append(param)
        else:
            assert False
            break

    if params and params[0] == 'void':
        del params[0]

    return params

def postProcessParameters(fns):
    fns.sort(key=lambda x: x['name'])
    for fn in fns:
        fn['params_full'] = list(fn['params'])
        for i in range(len(fn['params'])):
            p = fn['params'][i]
            if p.find('(') != -1:
                p = re.sub(r'\* *([a-zA-Z0-9_]*) ?\)', '*)', p, 1)
                fn['params'][i] = p
                continue
            parts = re.findall(r'[a-z_A-Z0-9]+|\*', p)
            if len(parts) > 1 and parts[-1].find('*') == -1:
                del parts[-1]
            fn['params'][i] = ' '.join(parts)

def readFunctionFilter(fns, fileName):
    try:
        f = open(fileName, "r")
    except:
        print(f"ERROR: Can't open filter file: {fileName}")
        return 0

    count = 0
    while f:
        line = f.readline()
        if not line:
            break
        assert isinstance(line, str)
        if line.startswith('#') or line.startswith('//'):
            continue
        line = line.replace('\n', '')
        if len(line) == 0:
            continue
        found = False
        for fn in fns:
            if fn['name'] == line:
                found = True
                fn['enabled'] = True
        if not found:
            sys.exit(f"FATAL ERROR: Unknown function: {line}")
        count = count + 1
    f.close()
    return count

#
# Generator helpers
#

def outputToString(f):
    def wrapped(*args, **kwargs):
        from cStringIO import StringIO
        old_stdout = sys.stdout
        sys.stdout = str_stdout = StringIO()
        res = f(*args, **kwargs)
        assert res is None
        sys.stdout = old_stdout
        result = str_stdout.getvalue()
        result = re.sub(r'([^\n /]) [ ]+', r'\1 ', result)  # don't remove spaces at start of line
        result = re.sub(r' ,', ',', result)
        result = re.sub(r' \*', '*', result)
        result = re.sub(r'\( ', '(', result)
        result = re.sub(r' \)', ')', result)
        return result
    return wrapped

@outputToString
def generateFilterNames(fns):
    for fn in fns:
        print(f"{'' if 'enabled' in fn else '//'}{fn['name']}")
    print('#total %d' % len(fns))

callback_check = re.compile(r'([^\(]*\(.*)(\* *)(\).*\(.*\))')

def getTypeWithParam(t, p):
    if callback_check.match(t):
        return callback_check.sub(r'\1 *' + p + r'\3', t)
    return f'{t} {p}'

@outputToString
def generateStructDefinitions(fns, lprefix='opencl_fn', enumprefix='OPENCL_FN'):
    print(f'// generated by {os.path.basename(sys.argv[0])}')
    for fn in fns:
        commentStr = '' if 'enabled' in fn else '//'
        decl_args = [
            getTypeWithParam(t, 'p%d' % (i + 1))
            for i, t in enumerate(fn['params'])
        ]
        decl_args_str = '(' + (', '.join(decl_args)) + ')'
        print('%s%s%d(%s_%s, %s, %s)' % \
             (commentStr, lprefix, len(fn['params']), enumprefix, fn['name'], \
             ' '.join(fn['ret']), decl_args_str))
        print(commentStr + ('%s%s (%s *%s)(%s) =\n%s        %s_%s_switch_fn;' % \
            ((' '.join(fn['modifiers'] + ' ') if len(fn['modifiers']) > 0 else ''),
             ' '.join(fn['ret']), ' '.join(fn['calling']), fn['name'], ', '.join(fn['params']), \
             commentStr, enumprefix, fn['name'])))
        print(commentStr + ('static const struct DynamicFnEntry %s_definition = { "%s", (void**)&%s};' % (fn['name'], fn['name'], fn['name'])))
        print()

@outputToString
def generateStaticDefinitions(fns):
    print(f'// generated by {os.path.basename(sys.argv[0])}')
    for fn in fns:
        commentStr = '' if 'enabled' in fn else '//'
        decl_args = [
            getTypeWithParam(t, 'p%d' % (i + 1))
            for i, t in enumerate(fn['params'])
        ]
        decl_args_str = '(' + (', '.join(decl_args)) + ')'
        print(
            f"{commentStr}CL_RUNTIME_EXPORT {' '.join(fn['modifiers'] + ' ') if len(fn['modifiers']) > 0 else ''}{' '.join(fn['ret'])} ({' '.join(fn['calling'])} *{fn['name']}_pfn)({', '.join(fn['params'])}) = {fn['name']};"
        )

@outputToString
def generateListOfDefinitions(fns, name='opencl_fn_list'):
    print(f'// generated by {os.path.basename(sys.argv[0])}')
    print('static const struct DynamicFnEntry* %s[] = {' % (name))
    first = False
    for fn in fns:
        commentStr = '' if 'enabled' in fn else '//'
        if 'enabled' in fn:
            print(f"    &{fn['name']}_definition,")
        else:
            print(f"    NULL/*&{fn['name']}_definition*/,")
    print('};')

@outputToString
def generateEnums(fns, prefix='OPENCL_FN'):
    print(f'// generated by {os.path.basename(sys.argv[0])}')
    print('enum %s_ID {' % prefix)
    for (i, fn) in enumerate(fns):
        commentStr = '' if 'enabled' in fn else '//'
        print(commentStr + ('    %s_%s = %d,' % (prefix, fn['name'], i)))
    print('};')

@outputToString
def generateRemapOrigin(fns):
    print(f'// generated by {os.path.basename(sys.argv[0])}')
    for fn in fns:
        print(f"#define {fn['name']} {fn['name']}_")

@outputToString
def generateRemapDynamic(fns):
    print(f'// generated by {os.path.basename(sys.argv[0])}')
    for fn in fns:
        print(f"#undef {fn['name']}")
        commentStr = '' if 'enabled' in fn else '//'
        print(f"{commentStr}#define {fn['name']} {fn['name']}_pfn")

@outputToString
def generateFnDeclaration(fns):
    print(f'// generated by {os.path.basename(sys.argv[0])}')
    for fn in fns:
        commentStr = '' if 'enabled' in fn else '//'
        print(
            f"{commentStr}extern CL_RUNTIME_EXPORT {' '.join(fn['modifiers'])} {' '.join(fn['ret'])} ({' '.join(fn['calling'])} *{fn['name']})({', '.join(fn['params'] if 'params_full' not in fn else fn['params_full'])});"
        )

@outputToString
def generateTemplates(total, lprefix, switch_name, calling_convention=''):
    print(f'// generated by {os.path.basename(sys.argv[0])}')
    for sz in range(total):
        template_params = ['ID', '_R', 'decl_args']
        params = ['p%d' % (i + 1) for i in range(sz)]
        print('#define %s%d(%s) \\' % (lprefix, sz, ', '.join(template_params)))
        print('    typedef _R (%s *ID##FN)decl_args; \\' % (calling_convention))
        print('    static _R %s ID##_switch_fn decl_args \\' % (calling_convention))
        print('    { return ((ID##FN)%s(ID))(%s); } \\' % (switch_name, ', '.join(params)))
        print('')

@outputToString
def generateInlineWrappers(fns):
    print(f'// generated by {os.path.basename(sys.argv[0])}')
    for fn in fns:
        commentStr = '' if 'enabled' in fn else '//'
        print(f"#undef {fn['name']}")
        print(f"{commentStr}#define {fn['name']} {fn['name']}_fn")
        params = []
        call_params = []
        for i in range(len(fn['params'])):
            t = fn['params'][i]
            if t.find('*)') >= 0:
                p = re.sub(r'\*\)', (' *p%d)' % i), t, 1)
                params.append(p)
            else:
                params.append('%s p%d' % (t, i))
            call_params.append('p%d' % (i))

        if len(fn['ret']) == 1 and fn['ret'][0] == 'void':
            print(commentStr + ('inline void %s(%s) { %s_pfn(%s); }' \
                    % (fn['name'], ', '.join(params), fn['name'], ', '.join(call_params))))
        else:
            print(commentStr + ('inline %s %s(%s) { return %s_pfn(%s); }' \
                    % (' '.join(fn['ret']), fn['name'], ', '.join(params), fn['name'], ', '.join(call_params))))

def ProcessTemplate(inputFile, ctx, noteLine='//\n// AUTOGENERATED, DO NOT EDIT\n//'):
    with open(inputFile, "r") as f:
        if noteLine:
            print(noteLine)
        for line in f:
            if line.startswith('@'):
                assert line[-1] == '\n'
                line = line[:-1]  # remove '\n'
                assert line[-1] == '@'
                name = line[1:-1]
                assert name in ctx, name
                line = ctx[name] + ('\n' if len(ctx[name]) > 0 and ctx[name][-1] != '\n' else '')
            sys.stdout.write(line)
