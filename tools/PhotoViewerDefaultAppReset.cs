using System;
using System.Collections.Generic;
using System.Reflection;
using System.Security.Principal;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("Photo Viewer Default App Reset")]
[assembly: AssemblyDescription("Removes Photo Viewer and legacy Portable Photo Viewer file-association registration")]
[assembly: AssemblyCompany("Photo Viewer")]
[assembly: AssemblyProduct("Photo Viewer Default App Reset")]
[assembly: AssemblyVersion("1.0.1.0")]
[assembly: AssemblyFileVersion("1.0.1.0")]

internal static class PhotoViewerDefaultAppReset
{
    private const string ClassesPath = @"Software\Classes\";
    private const string AppName = "Photo Viewer";
    private const string ProgId = "PhotoViewer.Image";
    private const string ExeName = "PhotoViewer.exe";
    private const string AppPath = @"Software\Photo Viewer";
    private const string LegacyAppName = "Portable Photo Viewer";
    private const string LegacyProgId = "PortablePhotoViewer.Image";
    private const string LegacyExeName = "PortableMediaViewer.exe";
    private const string LegacyAppPath = @"Software\Portable Photo Viewer";

    private static readonly string[] ImageExtensions =
    {
        ".apng", ".avif", ".avifs", ".bmp", ".bw", ".dds", ".gif", ".icb", ".ico",
        ".j2c", ".j2k", ".jfif", ".jp2", ".jpc", ".jpe", ".jpeg", ".jpf", ".jpg",
        ".jpx", ".pbm", ".pcx", ".pgm", ".png", ".pnm", ".ppm", ".psd", ".qoi",
        ".ras", ".rgb", ".rgba", ".sgi", ".tga", ".tif", ".tiff", ".vda", ".vst",
        ".webp", ".xbm", ".xpm"
    };

    [STAThread]
    private static void Main(string[] args)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);

        bool silent = Array.Exists(args, value =>
            string.Equals(value, "/silent", StringComparison.OrdinalIgnoreCase));

        if (!silent)
        {
            DialogResult answer = MessageBox.Show(
                "Photo Viewer와 기존 Portable Photo Viewer의 기본 앱 등록을 정리합니다.\r\n\r\n" +
                "사진 파일, 사용자 설정, 다른 프로그램의 등록은 삭제하지 않습니다.\r\n" +
                "계속하시겠습니까?",
                "Photo Viewer 기본 앱 정리",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Question,
                MessageBoxDefaultButton.Button2);

            if (answer != DialogResult.Yes)
                return;
        }

        int cleanedUser = 0;
        int cleanedMachine = 0;
        int protectedChoices = 0;
        var errors = new List<string>();

        try
        {
            cleanedUser = CleanRoot(Registry.CurrentUser);
            protectedChoices = CountProtectedChoices();
        }
        catch (Exception ex)
        {
            errors.Add("현재 사용자 등록: " + ex.Message);
        }

        if (IsAdministrator())
        {
            try
            {
                cleanedMachine = CleanRoot(Registry.LocalMachine);
            }
            catch (Exception ex)
            {
                errors.Add("전체 사용자 등록: " + ex.Message);
            }
        }

        string message =
            "정리가 완료되었습니다.\r\n\r\n" +
            "현재 사용자 등록 정리: " + cleanedUser + "개\r\n" +
            "전체 사용자 등록 정리: " + cleanedMachine + "개";

        if (!IsAdministrator())
            message += "\r\n전체 사용자 등록: 관리자 권한으로 실행할 때만 정리";

        if (protectedChoices > 0)
        {
            message += "\r\n\r\nWindows 보호 기본값 " + protectedChoices + "개는 유지됩니다." +
                       " 새 설치 후 해당 이미지가 새 설치 경로로 열리며," +
                       " 변경이 필요하면 이미지 더블클릭의 앱 선택에서 바꿀 수 있습니다.";
        }

        if (errors.Count > 0)
            message += "\r\n\r\n확인 필요:\r\n" + string.Join("\r\n", errors.ToArray());

        if (!silent)
        {
            MessageBox.Show(
                message,
            "Photo Viewer 기본 앱 정리",
                MessageBoxButtons.OK,
                errors.Count == 0 ? MessageBoxIcon.Information : MessageBoxIcon.Warning);
        }

        Environment.ExitCode = errors.Count == 0 ? 0 : 1;
    }

    private static int CleanRoot(RegistryKey root)
    {
        return CleanRegistration(root, AppName, ProgId, ExeName, AppPath) +
               CleanRegistration(root, LegacyAppName, LegacyProgId, LegacyExeName, LegacyAppPath);
    }

    private static int CleanRegistration(
        RegistryKey root,
        string appName,
        string progId,
        string exeName,
        string appPath)
    {
        int changes = 0;
        string backupPath = appPath + @"\Installer\PreviousAssociations";

        foreach (string extension in ImageExtensions)
        {
            string extensionPath = ClassesPath + extension;
            string previous = ReadString(root, backupPath, extension);
            string current = ReadString(root, extensionPath, null);

            if (string.Equals(current, progId, StringComparison.OrdinalIgnoreCase))
            {
                using (RegistryKey key = root.OpenSubKey(extensionPath, true))
                {
                    if (key != null)
                    {
                        if (!string.IsNullOrEmpty(previous) && previous != "<none>")
                            key.SetValue(null, previous, RegistryValueKind.String);
                        else
                            key.DeleteValue(null, false);
                        changes++;
                    }
                }
            }

            changes += DeleteValue(root, extensionPath + @"\OpenWithProgids", progId);
            changes += DeleteValue(root, ClassesPath + @"Applications\" + exeName + @"\SupportedTypes", extension);
            changes += DeleteValue(root, appPath + @"\Capabilities\FileAssociations", extension);
            changes += DeleteValue(root, backupPath, extension);
        }

        changes += DeleteValue(root, @"Software\RegisteredApplications", appName);
        changes += DeleteTree(root, ClassesPath + progId);
        changes += DeleteTree(root, ClassesPath + @"Applications\" + exeName);
        changes += DeleteTree(root, appPath + @"\Capabilities");
        DeleteEmptyTree(root, appPath + @"\Installer\PreviousAssociations");
        DeleteEmptyTree(root, appPath + @"\Installer");
        DeleteEmptyTree(root, appPath);
        return changes;
    }

    private static int CountProtectedChoices()
    {
        int count = 0;
        foreach (string extension in ImageExtensions)
        {
            string path = @"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\" +
                          extension + @"\UserChoice";
            string selected = ReadString(Registry.CurrentUser, path, "ProgId");
            if (string.Equals(selected, ProgId, StringComparison.OrdinalIgnoreCase) ||
                string.Equals(selected, LegacyProgId, StringComparison.OrdinalIgnoreCase))
                count++;
        }
        return count;
    }

    private static string ReadString(RegistryKey root, string path, string name)
    {
        using (RegistryKey key = root.OpenSubKey(path, false))
            return key == null ? null : key.GetValue(name, null) as string;
    }

    private static int DeleteValue(RegistryKey root, string path, string name)
    {
        using (RegistryKey key = root.OpenSubKey(path, true))
        {
            if (key == null || key.GetValue(name, null) == null)
                return 0;
            key.DeleteValue(name, false);
            return 1;
        }
    }

    private static int DeleteTree(RegistryKey root, string path)
    {
        using (RegistryKey key = root.OpenSubKey(path, false))
        {
            if (key == null)
                return 0;
        }
        root.DeleteSubKeyTree(path, false);
        return 1;
    }

    private static void DeleteEmptyTree(RegistryKey root, string path)
    {
        using (RegistryKey key = root.OpenSubKey(path, false))
        {
            if (key == null || key.SubKeyCount != 0 || key.ValueCount != 0)
                return;
        }
        root.DeleteSubKey(path, false);
    }

    private static bool IsAdministrator()
    {
        WindowsIdentity identity = WindowsIdentity.GetCurrent();
        WindowsPrincipal principal = new WindowsPrincipal(identity);
        return principal.IsInRole(WindowsBuiltInRole.Administrator);
    }
}
