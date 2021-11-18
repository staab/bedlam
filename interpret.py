import json, sys, functools


def interpret(ast, **kw):
    scope = _builtins.copy()
    scope.update(kw)

    try:
        for node in ast:
            result = evaluate(node, {'scope': scope})
    except InterpreterReturn as exc:
        return exc.args[0]

    return result


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

    if max is not None and n < max:
        raise InterpeterError("Incorrect number of arguments passed", node)

    return args


def derive_node(node, type, value):
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
    return [evaluate(x, context) for x in node['value']]


@define_key('map', _handlers)
def handle_map(node, context):
    value = node['value']

    return {
        evaluate(value[i], context): evaluate(value[i + 1], context)
        for i in range(0, len(value), 2)
    }


# Builtins


_builtins = {}


@define_key('defn', _builtins)
def fn_defn(args, node, context):
    name, params, body = assert_arity(node, args, min=3)

    for param in params['value']:
        if param['type'] != 'identifier':
            raise InterpeterError(f"Invalid function parameter {param['value']}", param)

    def f(caller_args, caller_node, caller_context):
        return evaluate(body, {
            'parent': context,
            'scope': {
                param['value']: evaluate(caller_args[i], caller_context)
                for i, param in enumerate(params['value'])
            },
        })

    context['scope'][name['value']] = f


@define_key('fn', _builtins)
def fn_fn(args, node, context):
    params, body = assert_arity(node, args, min=2)

    for param in params['value']:
        if param['type'] != 'identifier':
            raise InterpeterError(f"Invalid function parameter {param['value']}", param)

    def f(caller_args, caller_node, caller_context):
        return evaluate(body, {
            'parent': context,
            'scope': {
                param['value']: evaluate(caller_args[i], caller_context)
                for i, param in enumerate(params['value'])
            },
        })

    return f


@define_key('partial', _builtins)
def fn_partial(args, node, context):
    name, *args = assert_arity(node, args, min=2)

    def f(caller_args, caller_node, caller_context):
        return evaluate(derive_node(node, 'call', [name] + args + caller_args), context)

    return f


@define_key('apply', _builtins)
def fn_apply(args, node, context):
    f, args = assert_arity(node, args, exact=2)

    return evaluate(derive_node(node, 'call', [f] + args['value']), context)


@define_key('map', _builtins)
def fn_map(args, node, context):
    f, args = assert_arity(node, args, exact=2)

    return [
        evaluate(derive_node(node, 'call', [f, arg]), context)
        for arg in args['value']
    ]


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


@define_key('inc', _builtins)
def fn_inc(args, node, context):
    [n] = assert_arity(node, args, exact=1)

    return evaluate(n, context) + 1


@define_key('dec', _builtins)
def fn_dec(args, node, context):
    [n] = assert_arity(node, args, exact=1)

    return evaluate(n, context) - 1


@define_key('+', _builtins)
def fn_minus(args, node, context):
    return sum([evaluate(arg, context) for arg in args])


@define_key('-', _builtins)
def fn_minus(args, node, context):
    a, b = assert_arity(node, args, exact=2)

    return evaluate(a, context) - evaluate(b, context)


@define_key('*', _builtins)
def fn_multiply(args, node, context):
    xs = assert_arity(node, args, min=1)

    return functools.reduce(lambda r, x: r * evaluate(x, context), xs, 1)


@define_key('/', _builtins)
def fn_divide(args, node, context):
    a, b = assert_arity(node, args, exact=2)
    a = evaluate(a, context)
    b = evaluate(b, context)

    if b == 0:
        raise InterpeterError("Division by zero")

    return a / b


if __name__ == '__main__':
    print(json.dumps(interpret(json.loads(sys.argv[1])), indent=2))
