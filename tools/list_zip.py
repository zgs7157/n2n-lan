import zipfile, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
z = zipfile.ZipFile(r'C:\Users\Administrator\DoubaoWork\chats\2026-10-08\new-chat\n2n-lan\n2n-lan-client.zip')
print('entries:', len(z.namelist()))
for n in z.namelist():
    print(' ', n, z.getinfo(n).file_size)
