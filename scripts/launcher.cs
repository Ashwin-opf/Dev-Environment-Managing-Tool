using System;
using System.Diagnostics;
using System.IO;

class Program {
    static void Main() {
        try {
            string rootDir = @"C:\Users\srira\.gemini\antigravity\scratch\pc-doc";
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = "cmd.exe";
            psi.Arguments = "/c node scripts/start.js";
            psi.WorkingDirectory = rootDir;
            psi.CreateNoWindow = true;
            psi.UseShellExecute = false;
            psi.WindowStyle = ProcessWindowStyle.Hidden;

            string nodePath = @"C:\Program Files\nodejs";
            string currentPath = Environment.GetEnvironmentVariable("PATH") ?? "";
            if (!currentPath.Contains(nodePath)) {
                psi.EnvironmentVariables["PATH"] = nodePath + ";" + currentPath;
            }

            Process.Start(psi);
        } catch { }
    }
}
