import zipfile, io, sys, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
z = zipfile.ZipFile(os.path.join(ROOT, 'n2n-lan-client.zip'))
print('entries:', len(z.namelist()))
for n in z.namelist():
    print(' ', n, z.getinfo(n).file_size)
