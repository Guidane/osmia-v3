"""Storing uploaded files. Pictures are turned upright, scaled down to at most
2000 px and re-encoded (which drops camera and GPS metadata); other files are
kept as they are. Files are served to logged-in people only (core.views)."""
import io
import mimetypes
import os
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db.models import Max
from django.utils.text import get_valid_filename

MAX_SIZE = 20 * 1024 * 1024
MAX_PIXELS = 2000
IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/bmp', 'image/tiff'}
ALLOWED = {
    '.pdf', '.txt', '.csv', '.md', '.json', '.xml', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt', '.ods',
    '.odp', '.zip', '.7z', '.step', '.stp', '.iges', '.igs', '.stl', '.dxf', '.dwg', '.jpg', '.jpeg', '.png', '.gif',
    '.webp', '.bmp', '.tif', '.tiff', '.svg', '.kicad_sch', '.kicad_pcb', '.log',
}


def store(record, field, upload, user):
    from .models import Attachment
    name = get_valid_filename(os.path.basename(upload.name)) or 'file'
    ext = Path(name).suffix.lower()
    if upload.size > MAX_SIZE:
        raise ValidationError(f'{name} is larger than 20 MB.')
    if ext not in ALLOWED:
        raise ValidationError(f'{name}: files of type {ext or "(none)"} can\'t be added.')
    if field is not None and field.opt('images_only') and ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tif', '.tiff'):
        raise ValidationError(f'{field.name} takes pictures only.')
    content_type = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    content, is_image = upload, False
    if content_type in IMAGE_TYPES and content_type != 'image/gif':
        content, name, content_type, is_image = _prepare_image(upload, name, content_type)
    elif content_type == 'image/gif':
        is_image = True
    top = Attachment.objects.filter(record=record).aggregate(m=Max('position'))['m'] or 0
    attachment = Attachment(record=record, field=field, name=name, content_type=content_type, is_image=is_image,
                            uploaded_by=user, position=top + 1)
    attachment.file.save(name, content, save=False)
    attachment.size = attachment.file.size
    attachment.save()
    return attachment


def _prepare_image(upload, name, content_type):
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        image = Image.open(upload)
        image = ImageOps.exif_transpose(image)
    except (UnidentifiedImageError, OSError):
        raise ValidationError(f'{name} is not a picture that can be read.')
    image.thumbnail((MAX_PIXELS, MAX_PIXELS))
    out = io.BytesIO()
    if image.mode in ('RGBA', 'LA', 'P') and content_type == 'image/png':
        image.save(out, 'PNG', optimize=True)
        new_type, ext = 'image/png', '.png'
    else:
        image.convert('RGB').save(out, 'JPEG', quality=88, optimize=True)
        new_type, ext = 'image/jpeg', '.jpg'
    return ContentFile(out.getvalue()), Path(name).stem + ext, new_type, True


def thumbnail_path(attachment, size=320):
    """A small JPEG of a picture, made the first time it's asked for."""
    from PIL import Image
    target = Path(settings.MEDIA_ROOT) / 'thumbs' / f'{attachment.pk}-{size}.jpg'
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with attachment.file.open('rb') as f:
            image = Image.open(f)
            image.thumbnail((size, size))
            image.convert('RGB').save(target, 'JPEG', quality=80)
    return target
