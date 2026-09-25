using IsleWarden.Core;
using Xunit;

namespace IsleWarden.Core.Tests;

public class VdfParserTests
{
    [Fact]
    public void ParsesNestedManifest()
    {
        const string acf =
            """
            "AppState"
            {
                "appid"     "376210"
                "name"      "The Isle"
                "installdir" "The Isle"
                "buildid"   "24664737"
                "InstalledDepots"
                {
                    "376212" { "manifest" "7022929010820895867" }
                }
            }
            """;

        var root = VdfParser.Parse(acf);
        var state = root["AppState"];

        Assert.NotNull(state);
        Assert.Equal("376210", state!.GetString("appid"));
        Assert.Equal("The Isle", state.GetString("installdir"));
        Assert.Equal("24664737", state.GetString("buildid"));
        Assert.Equal("7022929010820895867", state["InstalledDepots"]?["376212"]?.GetString("manifest"));
    }

    [Fact]
    public void ParsesLibraryFoldersWithPaths()
    {
        const string vdf =
            """
            "libraryfolders"
            {
                "0"
                {
                    "path"  "C:\\Program Files (x86)\\Steam"
                    "apps"  { "376210" "10392313233" }
                }
                "1"
                {
                    "path"  "D:\\SteamLibrary"
                }
            }
            """;

        var libraries = VdfParser.Parse(vdf)["libraryfolders"];

        Assert.Equal(@"C:\Program Files (x86)\Steam", libraries?["0"]?.GetString("path"));
        Assert.Equal(@"D:\SteamLibrary", libraries?["1"]?.GetString("path"));
    }

    [Fact]
    public void HandlesCommentsAndIsCaseInsensitive()
    {
        const string vdf =
            """
            "Root"
            {
                // dòng chú thích
                "Key"  "value"
            }
            """;

        var root = VdfParser.Parse(vdf);
        Assert.Equal("value", root["root"]?.GetString("key"));
    }
}
