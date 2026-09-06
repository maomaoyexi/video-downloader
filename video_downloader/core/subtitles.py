def subtitle_result_has_file(output):
    return (
        "Writing video subtitles to:" in output
        or ("Video subtitle " in output and " is already present" in output)
    )


def subtitle_result_has_no_match(output):
    normalized = output.lower()
    return (
        "there are no subtitles for the requested languages" in normalized
        or "skipping writing video subtitles" in normalized
    )


def classify_subtitle_result(returncode, output):
    if returncode != 0:
        return "error"
    if subtitle_result_has_file(output):
        return "success"
    if subtitle_result_has_no_match(output):
        return "missing"
    return "missing"
