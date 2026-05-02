import psutil


def collect_system_metrics() -> dict[str, float]:
    cpu_percent = psutil.cpu_percent(interval=1.0)
    memory_percent = psutil.virtual_memory().percent
    disk_percent = psutil.disk_usage("/").percent

    return {
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "disk_percent": disk_percent,
    }
