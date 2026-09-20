import sys

def generate_resc(num_nodes):
    content = ""
    for i in range(1, num_nodes + 1):
        content += f"""
mach create "haven_{i}"
machine LoadPlatformDescription @renode/haven.repl
sysbus LoadELF @firmware/build/haven.elf
emulation CreateUartPtyTerminal "uart{i}" "/tmp/haven_uart_{i}" true
connector Connect sysbus.uart uart{i}
"""

    content += "\nstart\n"
    
    with open("renode/haven_multi.resc", "w") as f:
        f.write(content)

if __name__ == "__main__":
    num_nodes = 3
    if len(sys.argv) > 1:
        num_nodes = int(sys.argv[1])
    generate_resc(num_nodes)

