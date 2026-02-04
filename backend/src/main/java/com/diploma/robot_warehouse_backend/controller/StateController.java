package com.diploma.robot_warehouse_backend.controller;

import com.diploma.robot_warehouse_backend.dto.SlotStateResponse;
import com.diploma.robot_warehouse_backend.service.ShelfStateService;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api")
public class StateController {

    private final ShelfStateService shelfStateService;

    public StateController(ShelfStateService shelfStateService) {
        this.shelfStateService = shelfStateService;
    }

    @GetMapping("/state")
    public List<SlotStateResponse> state() {
        return shelfStateService.getState();
    }
}
