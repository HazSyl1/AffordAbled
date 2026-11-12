import { Camera, CameraResultType, CameraSource } from '@capacitor/camera';
import { Capacitor } from '@capacitor/core';

export async function pickNativeReceiptImage(): Promise<File | null> {
  try {
    const photo = await Camera.getPhoto({
      source: CameraSource.Prompt,
      resultType: CameraResultType.Uri,
      quality: 90,
      width: 2400,
      height: 2400,
      correctOrientation: true,
      saveToGallery: false,
      promptLabelHeader: 'Add a receipt',
      promptLabelPhoto: 'Photo Library',
      promptLabelPicture: 'Take Photo',
    });
    if (!photo.webPath) throw new Error('The selected photo could not be opened. Please try again.');
    const response = await fetch(photo.webPath);
    if (!response.ok) throw new Error('The selected photo could not be read. Please try again.');
    const blob = await response.blob();
    const format = photo.format === 'jpg' ? 'jpeg' : photo.format;
    return new File([blob], `receipt-${Date.now()}.${format}`, { type: `image/${format}` });
  } catch (error) {
    const message = error instanceof Error ? error.message : String((error as { message?: string })?.message ?? error);
    if (/cancel(?:led|ed)?|no image picked/i.test(message)) return null;
    if (/permission|denied/i.test(message)) {
      throw new Error('Allow camera or photo access for AffordAbled in your phone Settings, then try again.', { cause: error });
    }
    throw error;
  }
}

export function isNativeImagePicker(): boolean {
  return Capacitor.isNativePlatform();
}

/** Convert large phone photos to an uploadable JPEG, with a bounded pixel count and file size. */
export async function prepareReceiptImage(file: File): Promise<File> {
  if (!file.size) throw new Error('This image is empty. Please choose another photo.');
  const source = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = source;
    await image.decode();
    const scale = Math.min(1, 2400 / Math.max(image.naturalWidth, image.naturalHeight));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Photo processing is unavailable. Please try a JPG or PNG image.');
    context.fillStyle = '#fff';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.9));
    if (!blob || blob.size > 10 * 1024 * 1024) {
      throw new Error('This photo is too large. Please choose a smaller image.');
    }
    return new File([blob], `${file.name.replace(/\.[^.]+$/, '') || 'receipt'}.jpg`, { type: 'image/jpeg' });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'EncodingError') {
      throw new Error('This photo format could not be read. Please choose a JPG or PNG image.', { cause: error });
    }
    throw error;
  } finally {
    URL.revokeObjectURL(source);
  }
}
