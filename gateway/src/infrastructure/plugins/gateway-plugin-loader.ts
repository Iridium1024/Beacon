export interface GatewayPluginManifest {
  name: string;
  version: string;
  entrypoint: string;
  hooks: string[];
}

export interface GatewayPluginLoader {
  discover(): Promise<GatewayPluginManifest[]>;
}

export class FilesystemGatewayPluginLoader implements GatewayPluginLoader {
  public constructor(private readonly pluginsDirectory: string) {}

  public async discover(): Promise<GatewayPluginManifest[]> {
    void this.pluginsDirectory;
    throw new Error("Gateway plugin discovery is intentionally undefined in this scaffold.");
  }
}
