# https://stackoverflow.com/questions/785519/how-do-i-remove-all-pyc-files-from-a-project/785534
find . -name "*.pyc" -exec rm -f {} \;