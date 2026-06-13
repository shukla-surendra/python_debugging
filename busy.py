import time

def expensive_function():
    while True:
        total = 0
        for i in range(10_000_000):
            total += i * i

if __name__ == "__main__":
    expensive_function()