using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;
[assembly: System.Reflection.AssemblyTitle("Listenote")]
[assembly: System.Reflection.AssemblyProduct("Listenote")]
[assembly: System.Reflection.AssemblyVersion("2.0.1.0")]
[assembly: System.Reflection.AssemblyFileVersion("2.0.1.0")]
[assembly: System.Reflection.AssemblyDescription("Listenote 课堂录音与笔记")]
class Launcher {
 static string Quote(string arg) {
  var result=new System.Text.StringBuilder("\"");int slashes=0;
  foreach(char ch in arg) {
   if(ch=='\\') {slashes++;continue;}
   if(ch=='"') {result.Append('\\',slashes*2+1);result.Append(ch);}
   else {result.Append('\\',slashes);result.Append(ch);}
   slashes=0;
  }
  result.Append('\\',slashes*2);result.Append('"');return result.ToString();
 }
 [STAThread] static void Main(string[] args) {
  string root=AppDomain.CurrentDomain.BaseDirectory;
  try {
   string python=Path.Combine(root,"runtime","pythonw.exe");
   string script=Path.Combine(root,"app","startup.py");
   if(!File.Exists(python)||!File.Exists(script)) throw new Exception("请先解压完整的软件包，保留 runtime、app、models 和 tools 文件夹。");
   string extra="";
   foreach(string arg in args) extra+=" "+Quote(arg);
   var p=new ProcessStartInfo(python,"\""+script+"\""+extra); p.WorkingDirectory=root;p.UseShellExecute=false;p.CreateNoWindow=true;
   Process.Start(p);
  } catch(Exception e) {MessageBox.Show(e.Message,"听课 Listenote",MessageBoxButtons.OK,MessageBoxIcon.Information);}
 }
}
