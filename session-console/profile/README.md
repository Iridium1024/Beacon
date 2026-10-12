# Local profile template

`npm run profile:prepare` creates the ignored `.runtime/dsh-home` profile from
this template, installs the exact `0.1.1-rc.2` DSH dependency, and links the
current package as the third bundle after `dsh-base` and `dsh-web-app`.

The empty profile patch is intentional: the package-owned
`cordis.patch.yml` is the reviewed bundle layer. Local overrides are not part of
the acceptance path.

