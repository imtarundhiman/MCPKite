from pathlib import PurePath


SUPPORTED_BINARY_RESOURCE_MIME_TYPES: dict[str, tuple[str, ...]] = {
    "text/plain": (".txt",),
    "text/markdown": (".md", ".markdown"),
    "text/csv": (".csv",),
    "application/json": (".json",),
    "application/xml": (".xml",),
    "application/pdf": (".pdf",),
    "application/rtf": (".rtf",),
    "application/msword": (".doc",),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        ".docx",
    ),
    "application/vnd.ms-excel": (".xls",),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
        ".xlsx",
    ),
    "application/vnd.ms-powerpoint": (".ppt",),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (
        ".pptx",
    ),
    "image/png": (".png",),
    "image/jpeg": (".jpg", ".jpeg"),
    "image/gif": (".gif",),
    "image/webp": (".webp",),
    "image/svg+xml": (".svg",),
}

MIME_TYPE_BY_EXTENSION = {
    extension: mime_type
    for mime_type, extensions in SUPPORTED_BINARY_RESOURCE_MIME_TYPES.items()
    for extension in extensions
}


def resolve_binary_resource_mime_type(
    file_name: str,
    declared_mime_type: str | None,
    reported_mime_type: str | None,
) -> str:
    extension = PurePath(file_name).suffix.lower()
    inferred_mime_type = MIME_TYPE_BY_EXTENSION.get(extension)
    mime_type = (declared_mime_type or inferred_mime_type or "").strip().lower()

    extensions = SUPPORTED_BINARY_RESOURCE_MIME_TYPES.get(mime_type)
    if extensions is None:
        raise ValueError(
            "Unsupported file type. Choose a supported document, text, data, or image format."
        )
    if extension not in extensions:
        raise ValueError(
            f"The {mime_type} type does not match the file extension "
            f"'{extension or 'none'}'."
        )

    reported = (reported_mime_type or "").strip().lower()
    if reported and reported not in {mime_type, "application/octet-stream"}:
        raise ValueError(
            f"The uploaded file reports {reported}, which does not match "
            f"the selected {mime_type} type."
        )

    return mime_type
