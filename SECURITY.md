# Seguridad

## Versiones compatibles

Solo la última versión publicada recibe correcciones de seguridad.

## Cómo notificar una vulnerabilidad

No abras un issue público para una vulnerabilidad. Usa los avisos de seguridad privados de GitHub:

1. Ve a la pestaña **Security** del repositorio.
2. Pulsa **Report a vulnerability**.
3. Describe el problema, los pasos para reproducirlo, la versión afectada y, si es posible, un PDF de prueba.

Los avisos privados solo los ven los mantenedores del proyecto. Si no puedes usar GitHub, abre un issue pidiendo un canal privado, sin incluir detalles técnicos ni archivos.

## Qué esperar

- Se confirma la recepción en un plazo de una semana.
- Se valora el impacto y se acuerda con quien informa un plazo de corrección y la forma de publicarla.
- Cuando la corrección esté disponible, se publica una nueva versión y se describe el problema en el CHANGELOG, con crédito a quien lo notificó si lo desea.

## Alcance

Son de interés, por ejemplo, los fallos que permitan ejecutar código o escribir fuera de lo previsto al abrir o guardar un PDF, al procesar archivos de Office o al ejecutar OCR, así como errores en el cifrado o en la gestión de contraseñas.

TrazoPDF no ofrece servicios en red ni cuentas, así que no aplican los problemas de servidor típicos. Los límites documentados en [docs/FEATURES.md](docs/FEATURES.md), como que no se valida la cadena de confianza de las firmas, no son vulnerabilidades, aunque sí se pueden reportar como mejoras.
