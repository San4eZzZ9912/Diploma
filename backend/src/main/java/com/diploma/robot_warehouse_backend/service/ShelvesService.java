package com.diploma.robot_warehouse_backend.service;

import com.diploma.robot_warehouse_backend.dto.ShelfCoordinatesResponse;
import com.diploma.robot_warehouse_backend.repository.ShelvesRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

@Service
public class ShelvesService {
    private final ShelvesRepository shelvesRepository;

    public ShelvesService(ShelvesRepository shelvesRepository) {
        this.shelvesRepository = shelvesRepository;
    }

    @Transactional(readOnly = true)
    public List<ShelfCoordinatesResponse> getShelvesCoordinates() {
        List<ShelfCoordinatesResponse> shelfCoordinates = shelvesRepository.findAll().stream().map(
                (shelf) -> new ShelfCoordinatesResponse(
                        shelf.getShelfCode(),
                        shelf.getMapX(),
                        shelf.getMapY(),
                        shelf.getMapYaw())).toList();

        return shelfCoordinates;
    }


}
