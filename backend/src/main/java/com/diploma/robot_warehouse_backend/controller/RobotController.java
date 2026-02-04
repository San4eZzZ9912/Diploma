package com.diploma.robot_warehouse_backend.controller;

import com.diploma.robot_warehouse_backend.dto.RobotClearRequest;
import com.diploma.robot_warehouse_backend.dto.RobotPlaceRequest;
import com.diploma.robot_warehouse_backend.service.ShelfStateService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/robot")
public class RobotController {

    private final ShelfStateService shelfStateService;

    public RobotController(ShelfStateService shelfStateService) {
        this.shelfStateService = shelfStateService;
    }

    @PostMapping("/place")
    public ResponseEntity<?> place(@RequestBody RobotPlaceRequest req) {
        shelfStateService.updateSlotState(req.getShelfCode(), req.getSide(), req.getLevel(), req.getCubeQr(), req.getRobotId());
        return ResponseEntity.ok().build();
    }

    @PostMapping("/clear")
    public ResponseEntity<?> clear(@RequestBody RobotClearRequest req) {
        shelfStateService.clearSlotState(req.getShelfCode(), req.getSide(), req.getLevel(), req.getRobotId());
        return ResponseEntity.ok().build();
    }

}
