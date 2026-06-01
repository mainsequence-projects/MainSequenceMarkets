from __future__ import annotations

import msm_pricing


def main() -> None:
    print("Optional pricing exports:")
    for export_name in msm_pricing.__all__:
        print(f"- {export_name}")


if __name__ == "__main__":
    main()
