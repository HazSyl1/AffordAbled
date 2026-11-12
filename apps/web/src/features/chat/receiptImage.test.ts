import { afterEach, describe, expect, it, vi } from 'vitest';

const camera = vi.hoisted(() => ({ getPhoto: vi.fn() }));
vi.mock('@capacitor/camera', () => ({
  Camera: camera, CameraResultType: { Uri: 'uri' }, CameraSource: { Prompt: 'PROMPT' },
}));

import { pickNativeReceiptImage, prepareReceiptImage } from './receiptImage';

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); camera.getPhoto.mockReset(); });

describe('native receipt selection', () => {
  it('reads the native local URL and supplies the upload MIME type', async () => {
    camera.getPhoto.mockResolvedValue({ webPath: 'https://localhost/_capacitor_file_/receipt.jpg', format: 'jpeg' });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true,
      blob: async () => new Blob(['photo'], { type: 'application/octet-stream' }) }));
    const file = await pickNativeReceiptImage();
    expect(file?.type).toBe('image/jpeg');
    expect(file?.size).toBe(5);
    expect(camera.getPhoto).toHaveBeenCalledWith(expect.objectContaining({ source: 'PROMPT', saveToGallery: false }));
  });
  it('treats camera and photo-library cancellation as no selection', async () => {
    camera.getPhoto.mockRejectedValue({ message: 'User cancelled photos app' });
    expect(await pickNativeReceiptImage()).toBeNull();
  });
  it('explains how to restore denied photo access', async () => {
    camera.getPhoto.mockRejectedValue(new Error('Permission denied'));
    await expect(pickNativeReceiptImage()).rejects.toThrow('phone Settings');
  });
});

describe('receipt upload preparation', () => {
  it('rejects an empty photo before decoding', async () => {
    await expect(prepareReceiptImage(new File([], 'receipt.jpg'))).rejects.toThrow('empty');
  });
  it('bounds a large phone image and converts it to JPEG with a correct filename', async () => {
    vi.stubGlobal('Image', class {
      naturalWidth = 6000; naturalHeight = 4000;
      decode = async () => {};
    });
    vi.stubGlobal('URL', { createObjectURL: vi.fn().mockReturnValue('blob:photo'), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      fillStyle: '', fillRect: vi.fn(), drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
    let dimensions: number[] = [];
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function (this: HTMLCanvasElement, callback) {
      dimensions = [this.width, this.height];
      callback(new Blob(['compressed'], { type: 'image/jpeg' }));
    });
    const file = await prepareReceiptImage(new File(['large image'], 'receipt.heic', { type: 'image/heic' }));
    expect(dimensions).toEqual([2400, 1600]);
    expect(file.name).toBe('receipt.jpg');
    expect(file.type).toBe('image/jpeg');
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:photo');
  });
});
