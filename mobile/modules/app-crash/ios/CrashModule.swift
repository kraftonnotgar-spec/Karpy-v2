import ExpoModulesCore

/// iOS keeps crash reports through the system (TestFlight / Xcode Organizer); this module only
/// stores fatal JavaScript errors so the app can offer to send them to the team.
public class CrashModule: Module {
  private var url: URL {
    FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("app-last-crash.txt")
  }

  public func definition() -> ModuleDefinition {
    Name("AppCrash")

    Function("recordJs") { (text: String) -> Bool in
      try? FileManager.default.createDirectory(at: self.url.deletingLastPathComponent(), withIntermediateDirectories: true)
      try? ("kind=javascript\n\n" + String(text.prefix(16000))).write(to: self.url, atomically: true, encoding: .utf8)
      return true
    }

    Function("read") { () -> String in
      (try? String(contentsOf: self.url, encoding: .utf8)) ?? ""
    }

    Function("clear") { () -> Bool in
      try? FileManager.default.removeItem(at: self.url)
      return true
    }
  }
}
