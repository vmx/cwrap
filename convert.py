from cwrap.config import Config, File
import sys

print sys.argv
if len(sys.argv) > 1:
    files = [File(f) for f in sys.argv[1:]]
else:
    files = [File('test.h')]

if __name__ == '__main__':
    #config = Config('gccxml', files=files, save_dir = 'result_gccxml')
    #config.generate()
    
    print '------------------------'
    print

    config_clang = Config('clang', files=files, save_dir = 'result_clang')
    config_clang.generate()
