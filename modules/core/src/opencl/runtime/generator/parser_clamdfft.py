#!/bin/python
# usage:
#     cat clAmdFft.h | $0
from __future__ import print_function
import sys, re;

from common import remove_comments, getTokens, getParameters, postProcessParameters


try:
    f = open(sys.argv[1], "r") if len(sys.argv) > 1 else sys.stdin
except:
    sys.exit("ERROR. Can't open input file")

fns = []

while True:
    line = f.readline()
    if len(line) == 0:
        break
    assert isinstance(line, str)
    line = line.strip()
    if line.startswith('CLAMDFFTAPI'):
        line = re.sub(r'\n', r'', line)
        while True:
            nl = f.readline()
            nl = nl.strip()
            nl = re.sub(r'\n', r'', nl)
            if len(nl) == 0:
                break;
            line += f' {nl}'

        line = remove_comments(line)

        parts = getTokens(line)

        modifiers = []
        ret = []
        calling = []

        i = 0
        while True:
            if parts[i] == "CLAMDFFTAPI":
                modifiers.append(parts[i])
            else:
                break
            i += 1
        while (i < len(parts)):
            if parts[i] != '(':
                ret.append(parts[i])
            else:
                del ret[-1]
                i -= 1
                break
            i += 1

        name = parts[i]
        i += 1;
        fn = {'modifiers': [], 'ret': ret, 'calling': calling, 'name': name}
        print(f'name={name}')

        params = getParameters(i, parts)

        if len(params) > 0 and params[0] == 'void':
            del params[0]

        fn['params'] = params
        # print 'params="'+','.join(params)+'"'

        fns.append(fn)

f.close()

print('Found %d functions' % len(fns))

postProcessParameters(fns)

from pprint import pprint
pprint(fns)

from common import *

filterFileName='./filter/opencl_clamdfft_functions.list'
numEnabled = readFunctionFilter(fns, filterFileName)

functionsFilter = generateFilterNames(fns)
filter_file = open(filterFileName, 'wb')
filter_file.write(functionsFilter)

ctx = {'CLAMDFFT_REMAP_ORIGIN': generateRemapOrigin(fns)}
ctx['CLAMDFFT_REMAP_DYNAMIC'] = generateRemapDynamic(fns)
ctx['CLAMDFFT_FN_DECLARATIONS'] = generateFnDeclaration(fns)

sys.stdout = open('../../../../include/opencv2/core/opencl/runtime/autogenerated/opencl_clamdfft.hpp', 'wb')
ProcessTemplate('template/opencl_clamdfft.hpp.in', ctx)

ctx['CL_FN_ENUMS'] = generateEnums(fns, 'OPENCLAMDFFT_FN')
ctx['CL_FN_SWITCH'] = generateTemplates(23, 'openclamdfft_fn', 'openclamdfft_check_fn', '')
ctx['CL_FN_ENTRY_DEFINITIONS'] = generateStructDefinitions(fns, 'openclamdfft_fn', 'OPENCLAMDFFT_FN')
ctx['CL_FN_ENTRY_LIST'] = generateListOfDefinitions(fns, 'openclamdfft_fn')
ctx['CL_NUMBER_OF_ENABLED_FUNCTIONS'] = '// number of enabled functions: %d' % (numEnabled)

sys.stdout = open('../autogenerated/opencl_clamdfft_impl.hpp', 'wb')
ProcessTemplate('template/opencl_clamdfft_impl.hpp.in', ctx)
