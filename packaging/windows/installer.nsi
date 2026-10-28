; Builds dist/Dynamic Bridge Setup.exe, the Windows installer for Dynamic Bridge.
; Build with NSIS 3 on macOS or Windows: makensis packaging/windows/installer.nsi
; (packaging/build.sh runs it when makensis is available).
Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"

!define ROOT "../.."
!define VERSION "0.1.3"
!define RESOLVE_SCRIPTS "$APPDATA\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\DynamicBridge"

Name "Dynamic Bridge"
OutFile "${ROOT}/dist/Dynamic Bridge Setup.exe"
; The After Effects companion goes into Program Files, which needs administrator rights.
RequestExecutionLevel admin
InstallDir "$PROGRAMFILES64\Dynamic Bridge"
BrandingText "Dynamic Bridge ${VERSION}"
SetCompressor /SOLID lzma

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "Dynamic Bridge"
VIAddVersionKey "FileDescription" "Dynamic Bridge installer"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "Dynamic Bridge"

!define MUI_ICON "dynamic-bridge.ico"
!define MUI_UNICON "dynamic-bridge.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "welcome.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "welcome.bmp"
!define MUI_ABORTWARNING

!define MUI_WELCOMEPAGE_TITLE "Dynamic Bridge"
!define MUI_WELCOMEPAGE_TEXT "Edit a DaVinci Resolve shot in After Effects, then place the render back on the clip as a new take.$\r$\n$\r$\nThis installs:$\r$\n$\r$\n  •  Two scripts under Workspace > Scripts in Resolve$\r$\n  •  A companion panel under File > Scripts in After Effects$\r$\n$\r$\nWorks with DaVinci Resolve 21 (Free or Studio) and After Effects.$\r$\n$\r$\nClose Resolve and After Effects before you continue."
!define MUI_FINISHPAGE_TITLE "Dynamic Bridge is installed"
!define MUI_FINISHPAGE_TEXT "1.  Open DaVinci Resolve and After Effects.$\r$\n$\r$\n2.  In After Effects, open Edit > Preferences > Scripting && Expressions and turn on Allow Scripts to Write Files and Access Network.$\r$\n$\r$\n3.  In Resolve, select a clip and choose Workspace > Scripts > Dynamic Bridge - Send to After Effects.$\r$\n$\r$\n4.  In After Effects, use File > Scripts > Resolve AE Bridge: animate, then click Render for Resolve.$\r$\n$\r$\n5.  Back in Resolve, choose Dynamic Bridge - Apply AE Render."

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Var AECount

Function .onInit
    SetShellVarContext all
FunctionEnd

Function un.onInit
    SetShellVarContext all
FunctionEnd

Section "Dynamic Bridge"
    ; Resolve menu entries. The library lives outside the Scripts tree so it never shows as a menu item.
    SetOutPath "${RESOLVE_SCRIPTS}"
    File "${ROOT}/resolve_lua/Dynamic Bridge - Send to After Effects.lua"
    File "${ROOT}/resolve_lua/Dynamic Bridge - Apply AE Render.lua"
    SetOutPath "$INSTDIR"
    File "/oname=dynamic_bridge.lib" "${ROOT}/resolve_lua/lib/dynamic_bridge.lua"
    File "${ROOT}/resolve_ae/create_composition.jsx"
    File "${ROOT}/resolve_ae/Resolve AE Bridge.jsx"
    File "${ROOT}/README.md"
    ; Keep a self-contained library beside the all-users Resolve menu entries.
    SetOutPath "${RESOLVE_SCRIPTS}\.dynamic-bridge"
    File "/oname=dynamic_bridge.lib" "${ROOT}/resolve_lua/lib/dynamic_bridge.lua"
    File "${ROOT}/resolve_ae/create_composition.jsx"
    File "${ROOT}/resolve_ae/Resolve AE Bridge.jsx"
    ; Hidden, like a dot folder on macOS, so Resolve is less likely to list it as a Scripts submenu.
    SetFileAttributes "${RESOLVE_SCRIPTS}\.dynamic-bridge" HIDDEN
    DetailPrint "Resolve scripts installed in ${RESOLVE_SCRIPTS}"

    ; Upgrade any per-user installation for the account running setup as well.
    ; Otherwise Resolve can continue loading its old per-user menu/library.
    SetShellVarContext current
    ${If} ${FileExists} "$APPDATA\Dynamic Bridge\dynamic_bridge.lib"
        SetOutPath "$APPDATA\Dynamic Bridge"
        File "/oname=dynamic_bridge.lib" "${ROOT}/resolve_lua/lib/dynamic_bridge.lua"
        File "${ROOT}/resolve_ae/create_composition.jsx"
        File "${ROOT}/resolve_ae/Resolve AE Bridge.jsx"
    ${EndIf}
    SetShellVarContext all

    ${IfNot} ${FileExists} "$PROGRAMFILES64\Blackmagic Design\DaVinci Resolve\Resolve.exe"
        DetailPrint "DaVinci Resolve was not found in Program Files."
        MessageBox MB_ICONINFORMATION|MB_OK "DaVinci Resolve was not found. The scripts are installed and appear in Workspace > Scripts once Resolve is installed." /SD IDOK
    ${EndIf}

    ; After Effects companion, for every installed version.
    StrCpy $AECount 0
    FindFirst $0 $1 "$PROGRAMFILES64\Adobe\Adobe After Effects*"
    ${DoWhile} $1 != ""
        ${If} ${FileExists} "$PROGRAMFILES64\Adobe\$1\Support Files\AfterFX.exe"
            SetOutPath "$PROGRAMFILES64\Adobe\$1\Support Files\Scripts"
            File "${ROOT}/resolve_ae/Resolve AE Bridge.jsx"
            DetailPrint "After Effects companion installed in $1"
            IntOp $AECount $AECount + 1
        ${EndIf}
        FindNext $0 $1
    ${Loop}
    FindClose $0
    ${If} $AECount == 0
        DetailPrint "After Effects was not found."
        MessageBox MB_ICONINFORMATION|MB_OK "After Effects was not found. The Resolve scripts are installed. Run this installer again after installing After Effects to add its companion panel." /SD IDOK
    ${EndIf}

    WriteUninstaller "$INSTDIR\Uninstall Dynamic Bridge.exe"
    WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayName" "Dynamic Bridge"
    WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayVersion" "${VERSION}"
    WriteRegStr HKLM "${UNINSTALL_KEY}" "Publisher" "Dynamic Bridge"
    WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\Uninstall Dynamic Bridge.exe"
    WriteRegStr HKLM "${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\Uninstall Dynamic Bridge.exe"'
    WriteRegStr HKLM "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
    WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoModify" 1
    WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
    Delete "${RESOLVE_SCRIPTS}\Dynamic Bridge - Send to After Effects.lua"
    Delete "${RESOLVE_SCRIPTS}\Dynamic Bridge - Apply AE Render.lua"
    FindFirst $0 $1 "$PROGRAMFILES64\Adobe\Adobe After Effects*"
    ${DoWhile} $1 != ""
        Delete "$PROGRAMFILES64\Adobe\$1\Support Files\Scripts\Resolve AE Bridge.jsx"
        FindNext $0 $1
    ${Loop}
    FindClose $0
    Delete "${RESOLVE_SCRIPTS}\.dynamic-bridge\dynamic_bridge.lib"
    Delete "${RESOLVE_SCRIPTS}\.dynamic-bridge\create_composition.jsx"
    Delete "${RESOLVE_SCRIPTS}\.dynamic-bridge\Resolve AE Bridge.jsx"
    RMDir "${RESOLVE_SCRIPTS}\.dynamic-bridge"
    Delete "$INSTDIR\dynamic_bridge.lib"
    Delete "$INSTDIR\create_composition.jsx"
    Delete "$INSTDIR\Resolve AE Bridge.jsx"
    Delete "$INSTDIR\README.md"
    Delete "$INSTDIR\Uninstall Dynamic Bridge.exe"
    RMDir "$INSTDIR"
    DeleteRegKey HKLM "${UNINSTALL_KEY}"
    ; Renders in Videos\Resolve AE Bridge are kept: Resolve timelines still use them as takes.
SectionEnd
