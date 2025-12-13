import compileall

if __name__ == '__main__':
    print('Compiling all .py files...')
    ok = compileall.compile_dir('.', force=True, quiet=1)
    print('Done. compiled:', ok)
