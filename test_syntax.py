import sys
import esprima
try:
    with open('script_only.js', 'r') as f:
        js = f.read()
        js = js.replace('<script>', '').replace('</script>', '')
        esprima.parseScript(js)
except Exception as e:
    print("ERROR:", e)
