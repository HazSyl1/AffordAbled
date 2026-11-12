import { useRef, useState, type RefObject } from 'react';

import { isNativeImagePicker, pickNativeReceiptImage } from './receiptImage';

export function useReceiptImagePicker(
  inputRef: RefObject<HTMLInputElement | null>,
  onSelected: (file: File | null) => Promise<void>,
  onError: (message: string) => void,
) {
  const pending = useRef(false);
  const [isPickingImage, setIsPickingImage] = useState(false);
  const pickImage = async () => {
    if (pending.current) return;
    if (!isNativeImagePicker()) {
      inputRef.current?.click();
      return;
    }
    pending.current = true;
    setIsPickingImage(true);
    try {
      const file = await pickNativeReceiptImage();
      if (file) await onSelected(file);
    } catch (error) {
      onError(error instanceof Error ? error.message : 'Could not open this photo. Please try again.');
    } finally {
      pending.current = false;
      setIsPickingImage(false);
    }
  };
  return { pickImage, isPickingImage };
}
