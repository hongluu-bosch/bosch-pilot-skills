# Configuration

## `config/project.json`

Created by `--init-project`. Contains:

```json
{
  "name": "Project",
  "customer_name": "customer",
  "project_root": "ProjectRoot",
  "base_dir": "<container>",
  "paths": {
    "input_xlsx": ".DCOM_AI/19Service_Toolkit_PRJ/inputs/<basename>.xlsx",
    "cubas_dem_dir": "rb/as/<customer>/core/app/dsm/Cubas_DEM",
    "arxml_file_pattern": "DemEnvData_RBAPLCUST_EcucValues{suffix}.arxml",
    "product_type_to_arxml_suffix": {
      "Common": "",
      "RBU": "_RBU",
      "IPB": "_IPB",
      "ESP": "_ESP",
      "DPB": "_DPB",
      "ESPCL": "_ESPCL"
    }
  }
}
```

## Product types

`product_types` must be supplied explicitly by the human operator via their
prompt when running `--init-project`. The toolkit maps each product type to
an ARXML file suffix using a fixed built-in table; the agent must not invent
or override these suffixes.

## Environment variables

No environment variables are used for project-root resolution. The current
working directory is always the project root.
| `SERVICE19_NO_REVIEW` | Set to `1` to skip review reports |
