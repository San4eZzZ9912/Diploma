package com.diploma.robot_warehouse_backend.service;

import com.diploma.robot_warehouse_backend.dto.SlotStateResponse;
import com.diploma.robot_warehouse_backend.entity.ShelfSlot;
import com.diploma.robot_warehouse_backend.enums.Level;
import com.diploma.robot_warehouse_backend.enums.Side;
import com.diploma.robot_warehouse_backend.entity.SlotState;
import com.diploma.robot_warehouse_backend.repository.ShelfSlotRepository;
import com.diploma.robot_warehouse_backend.repository.ShelfRepository;
import com.diploma.robot_warehouse_backend.repository.SlotStateRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

@Service
public class ShelfStateService {
    private final ShelfSlotRepository shelfSlotRepository;
    private final SlotStateRepository slotStateRepository;

    public ShelfStateService(ShelfSlotRepository shelfSlotRepository, SlotStateRepository slotStateRepository, ShelfRepository shelfRepository) {
        this.shelfSlotRepository = shelfSlotRepository;
        this.slotStateRepository = slotStateRepository;
    }

    @Transactional
    public void updateSlotState(String shelfCode, Side side, Level level, String cubeQr, String robotId) {
        String normalizedShelf = shelfCode == null ? null : shelfCode.trim().toUpperCase();

        ShelfSlot shelfSlot = shelfSlotRepository.findByShelf_ShelfCodeAndSideAndLevel(normalizedShelf, side, level).orElseThrow(
                () -> new IllegalArgumentException("ShelfSlot not found: shelf=" + shelfCode + ", side=" + side)
        );

        SlotState slotState = slotStateRepository.findById(shelfSlot.getId()).orElseGet(() -> {
            SlotState state = new SlotState(shelfSlot);
            return state;
        });


        slotState.setOccupied(true);
        slotState.setCubeQr(cubeQr);
        slotState.setUpdatedAt(LocalDateTime.now());
        slotState.setRobotId(robotId);

        slotStateRepository.save(slotState);
    }

    @Transactional(readOnly = true)
    public List<SlotStateResponse> getState () {
        return slotStateRepository.findAll().stream().map(st -> new SlotStateResponse(
                st.getSlot().getShelf().getShelfCode(),
                st.getSlot().getSide(),
                st.isOccupied(),
                st.getCubeQr(),
                st.getUpdatedAt()
        )).toList();
    }

    @Transactional
    public void clearSlotState(String shelfCode, Side side, Level level, String robotId) {
        String normalizedShelf = shelfCode == null ? null : shelfCode.trim().toUpperCase();

        ShelfSlot shelfSlot = shelfSlotRepository
                .findByShelf_ShelfCodeAndSideAndLevel(normalizedShelf, side, level)
                .orElseThrow(() -> new IllegalArgumentException(
                        "ShelfSlot not found: shelf=" + normalizedShelf + ", side=" + side));

        SlotState slotState = slotStateRepository.findById(shelfSlot.getId()).orElseGet(() -> {
            SlotState state = new SlotState(shelfSlot);
            return state;
        });

        slotState.setOccupied(false);
        slotState.setCubeQr(null);
        slotState.setUpdatedAt(LocalDateTime.now());
        slotState.setRobotId(robotId);

        slotStateRepository.save(slotState);
    }



}
