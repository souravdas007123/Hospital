import os

def list_files(startpath):
    # In folders ko tree mein nahi dikhana hai
    ignore_dirs = {'venv', 'env', '__pycache__', '.git', 'migrations', 'node_modules'}
    
    with open('project_tree.txt', 'w', encoding='utf-8') as f:
        for root, dirs, files in os.walk(startpath):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            level = root.replace(startpath, '').count(os.sep)
            indent = ' ' * 4 * (level)
            f.write(f"{indent}{os.path.basename(root)}/\n")
            subindent = ' ' * 4 * (level + 1)
            for file in files:
                if not file.endswith('.pyc'):
                    f.write(f"{subindent}{file}\n")

list_files('.')
print("Tree successfully project_tree.txt mein save ho gaya hai!")