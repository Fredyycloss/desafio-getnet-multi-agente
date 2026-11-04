import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import OperatorConsole from './OperatorConsole'
import './styles.css'

// /operador = human operator console; everything else = merchant assistant.
const isOperator = window.location.pathname.startsWith('/operador')
createRoot(document.getElementById('root')!).render(<React.StrictMode>{isOperator ? <OperatorConsole /> : <App />}</React.StrictMode>)
