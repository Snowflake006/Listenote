using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
class Launcher {
 [STAThread] static void Main(string[] args) {
  string root=AppDomain.CurrentDomain.BaseDirectory;
  try {
   string python=Path.Combine(root,"runtime","pythonw.exe");
   string script=Path.Combine(root,"app","startup.py");
   if(!File.Exists(python)||!File.Exists(script)) throw new Exception("请先解压完整的软件包，保留 runtime、app、models 和 tools 文件夹。");
   string extra=Array.IndexOf(args,"--screenshot")>=0?" --screenshot":"";
   var p=new ProcessStartInfo(python,"\""+script+"\""+extra); p.WorkingDirectory=root;p.UseShellExecute=false;p.CreateNoWindow=true;
   Process.Start(p);
  } catch(Exception e) {MessageBox.Show(e.Message,"听课 Listenote",MessageBoxButtons.OK,MessageBoxIcon.Information);}
 }
}
