import { StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { Provider } from 'react-redux'
import { RouterProvider } from 'react-router-dom'

import './styles/global.css'
import { AppInitializer } from './app/AppInitializer'
import { router } from './app/router'
import { store } from './app/store'
import { ThemeProvider } from './features/theme/ThemeProvider'
import { PageLoader } from './components/molecules/PageLoader'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Provider store={store}>
      <ThemeProvider>
        <AppInitializer>
          <Suspense fallback={<PageLoader />}>
            <RouterProvider router={router} />
          </Suspense>
        </AppInitializer>
      </ThemeProvider>
    </Provider>
  </StrictMode>,
)
