from django.core.exceptions import ValidationError
from django.core.files.images import get_image_dimensions

MAX_MB = 3
MIN_SIDE = 600


def validate_image(image):
    if image.size > MAX_MB * 1024 * 1024:
        raise ValidationError(f"Image must be smaller than {MAX_MB} MB.")

    width, height = get_image_dimensions(image)
    if not width or not height:
        raise ValidationError("This file is not a valid image.")
    if width < MIN_SIDE or height < MIN_SIDE:
        raise ValidationError(f"Image must be at least {MIN_SIDE} x {MIN_SIDE} px.")