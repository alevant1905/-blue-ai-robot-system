"""Flask route groups extracted from bluetools.py.

Each module exposes register(app) which attaches its routes. View-function
names are kept identical to the originals so Flask endpoint names (and
url_for targets) do not change. Shared mutable state stays in bluetools;
route modules access it via `import bluetools as bt` and attribute lookup
(`bt.NAME`) at request time — never `from bluetools import NAME`.
"""
