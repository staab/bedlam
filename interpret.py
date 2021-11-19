import json, sys, functools
from parse import parse


def interpret(ast, scope=None):
    scope = {} if scope is None else scope
    scope.update(_builtins)
    scope.update(_library)

    try:
        result = evaluate_all(ast, {'scope': scope})
    except InterpreterReturn as exc:
        return exc.args[0]

    return result[-1]


# Utils


def _get_root_context(context):
    while 'parent' in context:
        context = context['parent']

    return context


def assert_arity(node, args, exact=None, min=None, max=None):
    n = len(args)

    if exact is not None and n != exact:
        raise InterpeterError("Incorrect number of arguments passed", node)

    if min is not None and n < min:
        raise InterpeterError("Incorrect number of arguments passed", node)

    if max is not None and n > max:
        raise InterpeterError("Incorrect number of arguments passed", node)

    return args


def wrap(node, type, value):
    new_node = node.copy()
    new_node.update({'type': type, 'value': value})

    return new_node


class InterpeterError(Exception):
    def __init__(self, message, node):
        line = node['location']['line']
        column = node['location']['column']

        super(Exception, self).__init__(f"{message} (at line {line} column {column})")


class InterpreterReturn(Exception):
    pass


def define_key(name, scope):
    def wrap(f):
        scope[name] = f

    return wrap


# AST type handlers


def evaluate(node, context):
    handler = _handlers[node['type']]

    return handler(node, context)


def evaluate_all(nodes, context):
    result = []
    for node in nodes:
        result.append(evaluate(node, context))

    return result


_handlers = {}


@define_key('call', _handlers)
def handle_call(node, context):
    name, *args = node['value']

    fn = evaluate(name, context)

    if type(fn).__name__ != 'function':
        raise InterpeterError(f"{name['value']} is not a function", node)

    return fn(args, node, context)


@define_key('identifier', _handlers)
def handle_identifier(node, context):
    value = node['value']

    while context:
        if value in context['scope']:
            return context['scope'][value]

        context = context.get('parent')

    raise InterpeterError(f"Unable to resolve name {value}", node)


@define_key('any', _handlers)
def handle_any(node, context):
    return node['value']


@define_key('int', _handlers)
def handle_int(node, context):
    return node['value']


@define_key('float', _handlers)
def handle_float(node, context):
    return node['value']


@define_key('string', _handlers)
def handle_string(node, context):
    return node['value']


@define_key('vec', _handlers)
def handle_vec(node, context):
    return evaluate_all(node['value'], context)


@define_key('map', _handlers)
def handle_map(node, context):
    value = node['value']

    return {
        evaluate(value[i], context): evaluate(value[i + 1], context)
        for i in range(0, len(value), 2)
    }


# Builtins


_builtins = {'true': True, 'false': False, 'nil': None}


@define_key('defn', _builtins)
def fn_defn(args, node, context):
    name, *args = assert_arity(node, args, min=3)
    args = [wrap(node, 'identifier', 'fn')] + args

    context['scope'][name['value']] = evaluate(wrap(node, 'call', args), context)


@define_key('fn', _builtins)
def fn_fn(args, node, context):
    params, body = assert_arity(node, args, min=2)

    for param in params['value']:
        if param['type'] != 'identifier':
            raise InterpeterError(f"Invalid function parameter {param['value']}", param)

    def f(caller_args, caller_node, caller_context):
        new_scope = {}
        for i, param in enumerate(params['value']):
            if param['value'] == '&':
                rest = evaluate_all(caller_args[i:], caller_context)
                new_scope[params['value'][i + 1]['value']] = rest

                break

            new_scope[param['value']] = evaluate(caller_args[i], caller_context)

        if len(params['value']) > i + 2:
            raise InterpeterError(f"Only one rest argument should be defined", node)

        return evaluate(body, {'parent': context, 'scope': new_scope})

    return f


@define_key('partial', _builtins)
def fn_partial(args, node, context):
    name, *args = assert_arity(node, args, min=2)

    def f(caller_args, caller_node, caller_context):
        return evaluate(wrap(node, 'call', [name] + args + caller_args), context)

    return f


@define_key('apply', _builtins)
def fn_apply(args, node, context):
    f, args = assert_arity(node, args, exact=2)
    args = [wrap(node, 'any', x) for x in evaluate(args, context)]

    return evaluate(wrap(node, 'call', [f] + args), context)


@define_key('map', _builtins)
def fn_map(args, node, context):
    f, xs = assert_arity(node, args, exact=2)
    xs = evaluate(xs, context)

    return [
        evaluate(wrap(node, 'call', [f, wrap(node, 'any', x)]), context)
        for x in xs
    ]


@define_key('filter', _builtins)
def fn_filter(args, node, context):
    f, xs = assert_arity(node, args, exact=2)
    xs = evaluate(xs, context)

    return [
        x for x in xs
        if evaluate(wrap(node, 'call', [f, wrap(node, 'any', x)]), context)
    ]


@define_key('reduce', _builtins)
def fn_reduce(args, node, context):
    f, init, xs = assert_arity(node, args, exact=3)

    r = evaluate(init, context)
    for x in xs['value']:
        r = evaluate(wrap(node, 'call', [f, x, wrap(node, init['type'], r)]), context)

    return r


@define_key('let', _builtins)
def fn_let(args, node, context):
    params, body = assert_arity(node, args, min=2)
    pairs = params['value']

    return evaluate(body, {
        'parent': context,
        'scope': {
            pairs[i]['value']: evaluate(pairs[i + 1], context)
            for i in range(0, len(pairs), 2)
        },
    })


@define_key('if', _builtins)
def fn_if(args, node, context):
    condition, yes, no = assert_arity(node, args, exact=3)

    if evaluate(condition, context):
        return evaluate(yes, context)

    return evaluate(no, context)


@define_key('when', _builtins)
def fn_when(args, node, context):
    condition, yes = assert_arity(node, args, exact=2)

    if evaluate(condition, context):
        return evaluate(yes, context)


@define_key('case', _builtins)
def fn_case(args, node, context):
    value_node, *pairs = assert_arity(node, args, min=2)
    value = evaluate(value_node, context)

    if len(pairs) % 2 == 1:
        default = pairs[-1]
        pairs = pairs[:-1]

    for i in range(0, len(pairs), 2):
        if evaluate(pairs[i], context) == value:
            return evaluate(pairs[i + 1], context)

    if default:
        return evaluate(default, context)

    raise InterpeterError("Case failed to match", node)


@define_key('exit', _builtins)
def fn_exit(args, node, context):
    assert_arity(node, args, exact=1)

    raise InterpreterReturn(evaluate(args[0], context))


@define_key('join', _builtins)
def fn_join(args, node, context):
    sep, *args = assert_arity(node, args, min=1)

    return evaluate(sep, context).join([
        str(evaluate(arg, context)) for arg in args
    ])


@define_key('not', _builtins)
def fn_not(args, node, context):
    [x] = assert_arity(node, args, exact=1)

    return not evaluate(x, context)


@define_key('+', _builtins)
def fn_plus(args, node, context):
    return sum(evaluate_all(args, context))


@define_key('-', _builtins)
def fn_minus(args, node, context):
    a, b = evaluate_all(assert_arity(node, args, exact=2), context)

    return a - b


@define_key('*', _builtins)
def fn_multiply(args, node, context):
    xs = assert_arity(node, args, min=1)

    return functools.reduce(lambda r, x: r * evaluate(x, context), xs, 1)


@define_key('/', _builtins)
def fn_divide(args, node, context):
    a, b = evaluate_all(assert_arity(node, args, exact=2), context)

    if b == 0:
        raise InterpeterError("Division by zero", node)

    return a / b


@define_key('>', _builtins)
def fn_gt(args, node, context):
    a, b = evaluate_all(assert_arity(node, args, exact=2), context)

    return a > b


@define_key('<', _builtins)
def fn_gt(args, node, context):
    a, b = evaluate_all(assert_arity(node, args, exact=2), context)

    return a < b


@define_key('=', _builtins)
def fn_gt(args, node, context):
    a, b = evaluate_all(assert_arity(node, args, exact=2), context)

    return a == b


@define_key('or', _builtins)
def fn_gt(args, node, context):
    return any(evaluate_all(args, context))


@define_key('and', _builtins)
def fn_gt(args, node, context):
    return all(evaluate_all(args, context))


@define_key('nth', _builtins)
def fn_nth(args, node, context):
    xs, i = evaluate_all(assert_arity(node, args, exact=2), context)

    if type(xs) != list:
        raise InterpeterError("Can't get index of non-vector", node)

    return xs[i]


@define_key('slice', _builtins)
def fn_slice(args, node, context):
    xs, *slice_args = evaluate_all(assert_arity(node, args, min=2, max=4), context)

    if type(xs) != list:
        raise InterpeterError("Can't get slice of non-vector", node)

    return xs[slice(*slice_args)]


# Library


_library = {}

with open('library.bedlam', 'r') as f:
    interpret(parse(f.read()), _library)


# Main


if __name__ == '__main__':
    print(json.dumps(interpret(json.loads(sys.argv[1])), indent=2))
