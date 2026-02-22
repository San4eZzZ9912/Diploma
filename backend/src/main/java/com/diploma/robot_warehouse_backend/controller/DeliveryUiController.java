package com.diploma.robot_warehouse_backend.controller;

import com.diploma.robot_warehouse_backend.repository.ProductRepository;
import com.diploma.robot_warehouse_backend.service.DeliveryDispatchService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;

public class DeliveryUiController {
    private final DeliveryDispatchService deliveryDispatchService;
    private final ProductRepository productRepository;


    public DeliveryUiController(DeliveryDispatchService deliveryDispatchService, ProductRepository productRepository) {
        this.deliveryDispatchService = deliveryDispatchService;
        this.productRepository = productRepository;
    }

    @GetMapping
    public String getPageProducts(@RequestParam(required = false) String q)
}
