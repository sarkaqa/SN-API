import os
from datetime import datetime

class ResultLogger:
    def __init__(self, stat_key, stat_labels, log_dir="logs"):
        if not stat_labels:
            raise ValueError("stat_labels dictionary must be provided.")
        if not stat_key:
            raise ValueError("stat_key must be provided.")

        label = stat_labels.get(stat_key.lower(), stat_key.lower()).replace(" ", "_").lower()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"player_stats_results_{label}_{timestamp}.txt"
        self.filename = os.path.join(log_dir, filename)

        os.makedirs(log_dir, exist_ok=True)

        with open(self.filename, "w") as f:
            f.write("Player Stats Log\n")
            f.write("=" * 50 + "\n")

    def log_section(self, title):
        separator = "=" * 50
        content = f"\n{separator}\n{title}\n{separator}\n"
        print(content.strip())
        self._write_to_file(content)

    def log_line(self, line):
        print(line)
        self._write_to_file(line + "\n")

    def _write_to_file(self, text):
        with open(self.filename, "a") as f:
            f.write(text)
