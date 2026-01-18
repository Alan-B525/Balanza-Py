import sys
p = sys.argv[1]
with open(p, 'r', encoding='utf-8') as f:
    for i, l in enumerate(f, 1):
        print(f"{i:04d}: {l.rstrip()}")
