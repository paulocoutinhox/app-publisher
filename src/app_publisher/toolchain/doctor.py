import platform
import shutil


def inspect_tools(apple: bool, google: bool, capture: bool) -> dict[str, bool]:
    tools: list[str] = []
    if apple:
        tools.extend(["xcodebuild", "xcrun"] if capture else ["xcodebuild"])
    if google:
        tools.extend(["adb"] if capture else ["java"])
    return {tool: shutil.which(tool) is not None for tool in sorted(set(tools))}


def is_macos() -> bool:
    return platform.system() == "Darwin"
