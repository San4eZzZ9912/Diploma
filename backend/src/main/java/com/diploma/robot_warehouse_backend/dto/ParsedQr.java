package com.diploma.robot_warehouse_backend.dto;

import lombok.AllArgsConstructor;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
@AllArgsConstructor
public class ParsedQr {
    private String sku;
    private String manufacturer;
}
