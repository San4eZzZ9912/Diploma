package com.diploma.robot_warehouse_backend.controller;

import com.diploma.robot_warehouse_backend.dto.OutboundCreateResult;
import com.diploma.robot_warehouse_backend.entity.Product;
import com.diploma.robot_warehouse_backend.repository.ProductRepository;
import com.diploma.robot_warehouse_backend.service.OutboundService;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

import java.util.List;

@Controller
@RequestMapping("/outbounds")
public class OutboundUiController {
    private final OutboundService outboundService;
    private final ProductRepository productRepository;

    public OutboundUiController(OutboundService outboundService, ProductRepository productRepository) {
        this.outboundService = outboundService;
        this.productRepository = productRepository;
    }

    @GetMapping("/create")
    public String createForm(@RequestParam(required = false) String q, Model model) {
        List<Product> products = productRepository.findInStockByNameLike(q);
        model.addAttribute("q", q);
        model.addAttribute("products", products);
        return "outbounds/create";
    }

    @PostMapping("create")
    public String create(@RequestParam String externalRef,
                         @RequestParam Integer productId,
                         @RequestParam Integer quantity,
                         Model model) {
        try {
            OutboundCreateResult result = outboundService.createOutbound(externalRef, productId, quantity);
            model.addAttribute("ok, Outbound create. id=" + result.getOutboundId()
            + ", lines=" + result.getLinesCreated() + ", tasks=" + result.getTasksCreated());
        } catch (Exception e) {
            model.addAttribute("error", "Error: " + e.getMessage());
        }

        model.addAttribute("q", "");
        model.addAttribute("products", productRepository.findInStockByNameLike(""));
        return "outbounds/create";

    }
}
