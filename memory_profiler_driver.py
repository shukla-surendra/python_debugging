from memory_profiler import profile
import time

@profile
def process_data():
    data = []

    # Allocate memory
    for i in range(5):
        data.extend([i] * 1_000_000)
        time.sleep(0.5)

    # Free some memory
    del data[:2_000_000]
    time.sleep(1)

if __name__ == "__main__":
    process_data()