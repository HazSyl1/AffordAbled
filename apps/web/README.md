# AffordAbled web app

The AffordAbled frontend is built with React, TypeScript, Redux Toolkit Query, Tailwind CSS, and Vite.

## Development

From this directory:

```powershell
npm install
npm run dev
```

The app uses `http://localhost:8000` as its API by default. Set `VITE_API_BASE_URL` in a local `.env` file to use another API URL.

## Validation and production build

```powershell
npm run lint
npm run build
npm run preview
```

See the [repository README](../../README.md) for API setup and the [v1 release checklist](../../docs/V1_RELEASE_CHECKLIST.md) for release acceptance requirements.

## Capacitor native apps

The Capacitor wrapper lives in this directory. Build and sync the web bundle with:

```bash
npm run cap:build
```

Open the native projects with `npm run cap:android` or `npm run cap:ios`. Release mobile builds must set `VITE_API_BASE_URL` to the hosted HTTPS API; the default `http://localhost:8000` is only suitable for browser development. The API deployment must allow credentialed requests from the Capacitor origins (`https://localhost` for Android and `capacitor://localhost` for iOS) in addition to the hosted web origin.

The Android project can be built with Android Studio/SDK. The iOS project requires macOS and Xcode.
