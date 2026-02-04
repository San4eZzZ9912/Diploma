package com.diploma.robot_warehouse_backend.controller;

import com.diploma.robot_warehouse_backend.dto.ShelfCoordinatesResponse;
import com.diploma.robot_warehouse_backend.service.ShelfStateService;
import com.diploma.robot_warehouse_backend.service.ShelvesService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api")
public class ShelfController {

    private final ShelvesService shelvesService;

    public ShelfController(ShelvesService shelvesService) {
        this.shelvesService = shelvesService;
    }

    @GetMapping("/shelves")
    public List<ShelfCoordinatesResponse> coordinates() {
        return shelvesService.getShelvesCoordinates();
    }
}
