import sys, json, re


def parse(s):
    return build_ast(tokenize(s), {'line': 1, 'column': 0})


# Tokenize


def tokenize(s):
    segments = map(pre_tokenize, enumerate(re.sub(r'\\"', QUOTE, s).split('"')))
    tokens = re.split('[\s\n]+', '"'.join(segments).strip().replace(QUOTE, '"'))

    return list(tokens)


def pre_tokenize(x):
    i, segment = x

    # If we're in a string
    if i % 2 == 1:
        return segment.replace(' ', SPACE).replace('\n', NEWLINE)

    segment = re.sub(r' ', f' {SPACE} ', segment)
    segment = re.sub(r'\n', f' {NEWLINE} ', segment)
    segment = re.sub(r'([\(\)\[\]\{\},])', r' \1 ', segment)

    return segment


def placeholder(name):
    return f"__BEDLAM_{name}"


QUOTE = placeholder('QUOTE')
SPACE = placeholder('SPACE')
NEWLINE = placeholder('NEWLINE')


# Build AST


def build_ast(tokens, location):
    ast = []

    def add_node(type, value, token):
        ast.append({'type': type, 'value': value, 'location': location.copy()})

        new_lines = len([x for x in token if x == '\n'])

        location['line'] += new_lines
        location['column'] = 0 if new_lines else location['column'] + len(token)

    while tokens:
        token, *tokens = tokens

        if token in {')', ']', '}'}:
            return ast, tokens

        if token == NEWLINE:
            location['line'] += 1
            location['column'] = 0

            continue

        if token in {SPACE, ','}:
            location['column'] += 1

            continue

        if token in {'(', '[', '{'}:
            if token == '(':
                type = 'call'

            if token == '[':
                type = 'vec'

            if token == '{':
                type = 'map'

            children, tokens = build_ast(tokens, location)

            add_node(type, children, token)

            continue

        if token[0] == '"':
            add_node('string', token[1:-1].replace(SPACE, ' ').replace(NEWLINE, '\n'), token)

            continue

        try:
            add_node('int', int(token), token)

            continue
        except ValueError:
            pass

        try:
            add_node('float', float(token), token)

            continue
        except ValueError:
            pass

        add_node('identifier', token, token)

    return ast


if __name__ == '__main__':
    print(json.dumps(parse(sys.argv[1]), indent=2))
