export interface HealthSnapshot {
  status: "placeholder";
  gateway: "configured";
  core: "forwarding";
}

export interface HealthService {
  getStatus(): Promise<HealthSnapshot>;
}

export class PlaceholderHealthService implements HealthService {
  public async getStatus(): Promise<HealthSnapshot> {
    return {
      status: "placeholder",
      gateway: "configured",
      core: "forwarding",
    };
  }
}
