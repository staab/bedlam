import sys, json
from parse import parse
from interpret import interpret


def bedlam(script, **scope):
    return interpret(parse(script), **scope)


if __name__ == '__main__':
    print(json.dumps(bedlam(sys.argv[1]), indent=2))
