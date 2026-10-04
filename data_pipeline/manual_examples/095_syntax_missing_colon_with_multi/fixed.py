def copy_file(src, dst):
    with open(src) as fin, open(dst, "w") as fout:
        fout.write(fin.read())
