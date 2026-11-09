; Script de Inno Setup 6 para TrazoPDF.
; Normalmente se compila con installer\build-installer.ps1, que pasa la versión y la carpeta de origen:
;   ISCC.exe /DMyAppVersion=0.5.0 /DSourceDir="..\dist\TrazoPDF" pdf-editor.iss

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef MyAppVersionNumeric
  #define MyAppVersionNumeric "0.0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\TrazoPDF"
#endif

#define MyAppName "TrazoPDF"
#define MyAppExeName "TrazoPDF.exe"
#define MyAppPublisher "TrazoPDF"
#define MyAppURL "https://github.com/nmc03/trazopdf"

[Setup]
; El AppId identifica la aplicación entre versiones. No debe cambiar.
AppId={{6F2C1B7E-4A9D-4E3B-9C1A-2D8E5F7B3A10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
VersionInfoVersion={#MyAppVersionNumeric}
VersionInfoProductName={#MyAppName}
VersionInfoCompany={#MyAppPublisher}

; Instalación por usuario por defecto; el usuario puede elegir instalar para todos.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

LicenseFile=..\LICENSE
OutputDir=Output
OutputBaseFilename=TrazoPDF-{#MyAppVersion}-setup
SetupIconFile=..\assets\pdf-editor.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=yes
CloseApplications=yes
RestartApplications=no
ChangesAssociations=no

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Incluye también la carpeta "tesseract" (Tesseract OCR y sus DLL) que build.ps1 copia junto a la aplicación.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; Registra la aplicación en "Abrir con" para los PDF sin cambiar el manejador predeterminado.
; HKA apunta a HKCU con instalación por usuario y a HKLM con instalación para todos.
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}"; ValueType: none; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\shell\open"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#MyAppName}"
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
